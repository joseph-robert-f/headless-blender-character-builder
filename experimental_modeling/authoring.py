"""Explicit, journaled proposal-only model requests. Never executes model output."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_UP
from pathlib import Path
import secrets
import threading

from . import requests
from .request_contract import encoded, read_bytes, sha
from .controller import sync_directory

MAX_CONTEXT = 192 * 1024
MAX_PREVIEWS = 32
MODELS = ("gpt-4.1-mini", "gpt-4.1")


def money(value):
    if not isinstance(value, str) or len(value) > 24:
        raise ValueError("Use a decimal USD amount as text.")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("Use a finite positive USD amount.") from None
    if not number.is_finite() or not Decimal("0.000001") <= number <= Decimal("1000000"):
        raise ValueError("Use a USD amount from 0.000001 to 1000000.")
    return number


@dataclass(frozen=True)
class AuthorConfig:
    model: str
    input_usd_per_million: str
    output_usd_per_million: str
    budget_usd: str
    max_output_tokens: int = 8192
    max_calls: int = 8

    def __post_init__(self):
        if self.model not in MODELS:
            raise ValueError("Select a supported proposal model.")
        for value in (self.input_usd_per_million, self.output_usd_per_million, self.budget_usd):
            money(value)
        if type(self.max_output_tokens) is not int or not 256 <= self.max_output_tokens <= 16384:
            raise ValueError("Output token limit must be 256..16384.")
        if type(self.max_calls) is not int or not 1 <= self.max_calls <= 32:
            raise ValueError("Call limit must be 1..32.")

    def public(self):
        return {"provider": "openai", **self.__dict__, "currency": "USD",
                "budget_kind": "local_estimate_only", "endpoint": "https://api.openai.com/v1/responses"}


class Authoring:
    def __init__(self, workbench, config, provider=None):
        from .model_provider import OpenAIProvider
        self.wb = workbench
        self.config = config
        self.provider = provider if provider is not None else OpenAIProvider()
        self.active = None
        self.cancel = None
        self.thread = None
        self.closed = False

    def calls(self):
        return self.wb.records("modelcall")

    def call(self, row):
        result = dict(row)
        live = self.active == row["id"] and self.thread is not None and self.thread.is_alive()
        if row["state"] in {"claimed", "sending", "cancel_requested"} and not live:
            result["state"] = "uncertain"
        result["can_cancel"] = live
        return result

    def state(self):
        rows = self.calls()
        reserved = sum((money(row["reserved_usd"]) for row in rows), Decimal(0))
        return {"enabled": True, "config": self.config.public(),
                "reserved_usd": str(reserved), "calls": [self.call(row) for row in rows],
                "previews": [{key: row[key] for key in ("id", "digest", "handoff_label", "estimate_usd")}
                             for row in self.wb.records("modelpreview")]}

    def preview(self, payload):
        from .model_provider import create_request
        with self.wb.lock:
            self.wb.pinned()
            if set(payload) != {"csrf_token", "handoff_id"}:
                raise ValueError("Select one prepared handoff for a model preview.")
            if self.closed or len(self.wb.records("modelpreview")) >= MAX_PREVIEWS - 1:
                raise ValueError("Model preview limit reached or session closed.")
            handoff = self.wb.selected(payload["handoff_id"], "handoffs")
            request = requests.load_handoff(self.wb.project, handoff)
            requests.check_current(self.wb.project, request)
            files, total = {}, 0
            for name, expected in sorted(request["context_files"].items()):
                data = read_bytes(handoff / name, MAX_CONTEXT - total)
                total += len(data)
                if sha(data) != expected:
                    raise ValueError("Handoff changed during preview.")
                try:
                    files[name] = data.decode("utf-8")
                except UnicodeDecodeError:
                    raise ValueError("Direct authoring supports text context only. Use an external author for binary assets.") from None
            context = {"request": request, "files": files}
            if len(encoded(context)) > MAX_CONTEXT:
                raise ValueError("Direct authoring context exceeds 192 KiB.")
            outbound = create_request(self.config.model, encoded(context).decode(), self.config.max_output_tokens)
            # UTF-8 bytes plus a large protocol allowance is deliberately conservative
            # for text input. This is not a provider tokenizer or a billing guarantee.
            input_bound = len(encoded(outbound)) + 4096
            estimate = ((Decimal(input_bound) * money(self.config.input_usd_per_million) +
                         Decimal(self.config.max_output_tokens) * money(self.config.output_usd_per_million)) /
                        Decimal(1000000)).quantize(Decimal("0.000001"), rounding=ROUND_UP)
            value = {"id": secrets.token_hex(16), "handoff_label": handoff.name,
                     "handoff_id": payload["handoff_id"], "handoff_path": str(handoff),
                     "request_id": request["request_id"], "config": self.config.public(),
                     "outbound": outbound, "estimated_input_token_bound": input_bound,
                     "estimate_usd": str(estimate), "estimate_kind": "conservative_text_estimate_not_billing_limit"}
            value["digest"] = sha(encoded(value))
            self.wb.save("modelpreview", value)
            return value

    def submit(self, payload):
        with self.wb.lock:
            self.wb.pinned()
            if set(payload) != {"csrf_token", "preview_id", "digest", "approve_transmission"} or payload["approve_transmission"] is not True:
                raise ValueError("Approve the exact displayed context, recipient, model and estimate.")
            preview = self.wb.record("modelpreview", payload["preview_id"])
            if payload["digest"] != preview["digest"] or sha(encoded({k: v for k, v in preview.items() if k != "digest"})) != preview["digest"]:
                raise ValueError("Model preview digest changed.")
            rows = self.calls()
            existing = next((row for row in rows if row["id"] == preview["id"]), None)
            if existing:
                return self.call(existing)
            if self.closed or self.active is not None or any(row["state"] in {"claimed", "sending", "cancel_requested", "uncertain"} for row in rows):
                raise ValueError("A model call is active or uncertain. No new call can start.")
            if preview["config"] != self.config.public():
                raise ValueError("Provider settings changed. Make and review a new preview.")
            handoff = Path(preview["handoff_path"])
            if handoff.parent != self.wb.roots["handoffs"]:
                raise ValueError("Handoff is outside the selected root.")
            request = requests.load_handoff(self.wb.project, handoff)
            requests.check_current(self.wb.project, request)
            if request["request_id"] != preview["request_id"]:
                raise ValueError("Handoff no longer matches the preview.")
            if len(rows) >= self.config.max_calls or len(self.wb.catalogue()["proposals"]) >= 127:
                raise ValueError("The local call or proposal limit is reached.")
            reserved = sum((money(row["reserved_usd"]) for row in rows), Decimal(0))
            if reserved + money(preview["estimate_usd"]) > money(self.config.budget_usd):
                raise ValueError("The local estimated budget is insufficient. No call was sent.")
            row = {"id": preview["id"], "digest": preview["digest"], "state": "claimed",
                   "provider": "openai", "model": self.config.model, "reserved_usd": preview["estimate_usd"],
                   "usage": None, "detail": "One request reserved. No automatic retry.", "proposal_label": None}
            self.wb.save("modelcall", row)
            self.active = row["id"]
            self.cancel = threading.Event()
            self.thread = threading.Thread(target=self._generate, args=(preview, row, self.cancel), daemon=False)
            try:
                self.thread.start()
            except Exception:
                self.active = None
                raise ValueError("Model worker did not start. Reservation retained; no retry.") from None
            return self.call(row)

    def _generate(self, preview, row, cancel):
        from .model_provider import ProviderError, validate_proposal
        try:
            with self.wb.lock:
                if cancel.is_set():
                    row.update(state="cancelled", detail="Cancelled before provider invocation. Reservation retained.")
                    return
                self.wb.pinned()
                row.update(state="sending", detail="One bounded request is in progress. Cancellation may still incur charges.")
                self.wb.save("modelcall", row, replace=True)
            result = self.provider.generate(preview["outbound"], cancel)
            proposal = validate_proposal(result["proposal"])
            with self.wb.lock:
                row["usage"] = result["usage"]
                if cancel.is_set():
                    row.update(state="cancelled", detail="Cancellation observed. No proposal published. Charges may apply.")
                    return
                self.wb.pinned()
                # Do not silently rebase a proposal if the accepted parent changes.
                current = requests.load_handoff(self.wb.project, Path(preview["handoff_path"]))
                requests.check_current(self.wb.project, current)
                if current["request_id"] != preview["request_id"]:
                    raise ValueError("Handoff changed during generation.")
                output = self.wb.roots["proposals"] / ("model-" + row["id"])
                output.mkdir(mode=0o700)
                for file in proposal["source"]:
                    requests._write(output / "source" / file["name"], file["content"].encode("utf-8"))
                requests._write(output / "params.json", proposal["params_json"].encode("utf-8"))
                sync_directory(output / "source")
                sync_directory(output)
                sync_directory(output.parent)
                row.update(state="completed", proposal_label=output.name,
                           detail="Proposal saved. Select it and independently reviewed rules for inspection. No source was executed.")
        except ProviderError as error:
            row.update(state="uncertain" if error.code in {"cancelled", "timeout", "network_error"} else "failed", detail=str(error))
            row["usage"] = getattr(error, "usage", None)
        except Exception:
            row.update(state="failed", detail="Local proposal finalization failed. Reservation retained; examine partial proposal files. No automatic retry.")
        finally:
            with self.wb.lock:
                try:
                    self.wb.save("modelcall", row, replace=True)
                finally:
                    self.active = None

    def interrupt(self, payload):
        with self.wb.lock:
            if set(payload) != {"csrf_token", "call_id"}:
                raise ValueError("Select a recorded model call.")
            row = self.wb.record("modelcall", payload["call_id"])
            if self.active == row["id"] and self.cancel is not None:
                self.cancel.set()
                row.update(state="cancel_requested", detail="Cancellation requested. Charges may apply; no automatic retry.")
                self.wb.save("modelcall", row, replace=True)
            return self.call(row)

    def close(self):
        with self.wb.lock:
            self.closed = True
            if self.cancel is not None:
                self.cancel.set()
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join()
