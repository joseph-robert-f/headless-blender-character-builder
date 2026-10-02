/* SPDX-License-Identifier: GPL-3.0-or-later
 * Small, terminal-first x64 bootstrap. Only Windows OS APIs are linked.
 * No CRT startup, static CRT, downloader, runtime installer, or elevation.
 * Keep writable buffers and structs off the stack. /GS remains enabled;
 * /NODEFAULTLIB makes unexpected compiler runtime helpers a link failure.
 */
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0A00
#include <windows.h>

#define CAPACITY 32768u
#define EXIT_USAGE 64u
#define EXIT_INTERNAL 70u
#define EXIT_PREREQUISITE 78u

static WCHAR module_path[CAPACITY];
static WCHAR system_path[CAPACITY];
static WCHAR loaded_path[CAPACITY];
static WCHAR command_line[CAPACITY];
static STARTUPINFOEXW startup;
static PROCESS_INFORMATION child;
static JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits;
static SECURITY_ATTRIBUTES inherited;
static HANDLE standard_handles[3];
static HANDLE job;
static SIZE_T attribute_bytes;
static char number_text[11];

static DWORD wide_length(const WCHAR *text) {
    DWORD count = 0;
    while (count < CAPACITY && text[count]) ++count;
    return count;
}

static void stderr_text(const char *text) {
    DWORD count = 0, written = 0;
    HANDLE stream = GetStdHandle(STD_ERROR_HANDLE);
    while (text[count]) ++count;
    if (stream && stream != INVALID_HANDLE_VALUE) {
        /* Diagnostics are fixed ASCII; never interpret user input as formatting. */
        while (count && WriteFile(stream, text, count, &written, NULL) && written) {
            text += written;
            count -= written;
        }
    }
}

static void stderr_number(DWORD number) {
    DWORD end = 10;
    number_text[end] = '\0';
    do {
        number_text[--end] = (char)('0' + number % 10);
        number /= 10;
    } while (number);
    stderr_text(number_text + end);
}

static __declspec(noreturn) void fail(const char *operation, DWORD error, DWORD status) {
    stderr_text("HBCB REVIEW PREVIEW: ");
    stderr_text(operation);
    stderr_text(" (Windows error ");
    stderr_number(error);
    stderr_text(").\r\n");
    ExitProcess(status);
}

static BOOL append(WCHAR *destination, DWORD *length, const WCHAR *source) {
    while (*source) {
        if (*length >= CAPACITY - 1) return FALSE;
        destination[(*length)++] = *source++;
    }
    destination[*length] = L'\0';
    return TRUE;
}

static BOOL runtime_available(const WCHAR *name, const char *display, DWORD directory_length) {
    DWORD length = directory_length, error = 0, actual;
    HMODULE runtime;
    system_path[length] = L'\0';
    if (!append(system_path, &length, name)) {
        fail("System32 runtime path exceeds the launcher limit", ERROR_FILENAME_EXCED_RANGE, EXIT_INTERNAL);
    }
    /* An actual load tests transitive dependencies too. Do not use PATH,
     * SystemRoot, the working directory, registry guesses, or file existence. */
    runtime = LoadLibraryExW(system_path, NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!runtime) {
        error = GetLastError();
    } else {
        actual = GetModuleFileNameW(runtime, loaded_path, CAPACITY);
        if (!actual || actual >= CAPACITY) {
            error = actual ? ERROR_FILENAME_EXCED_RANGE : GetLastError();
        } else if (CompareStringOrdinal(system_path, -1, loaded_path, -1, TRUE) != CSTR_EQUAL) {
            /* Reject application-local redirection instead of accepting it as
             * evidence that the prerequisite is installed in System32. */
            error = ERROR_BAD_PATHNAME;
        }
        FreeLibrary(runtime);
    }
    if (error) {
        stderr_text("HBCB REVIEW PREVIEW: cannot load ");
        stderr_text(display);
        stderr_text(" from Windows System32 (Windows error ");
        stderr_number(error);
        stderr_text(").\r\n");
        return FALSE;
    }
    return TRUE;
}

static void check_runtime(void) {
    DWORD length = GetSystemDirectoryW(system_path, CAPACITY);
    BOOL first, second;
    if (!length || length >= CAPACITY) {
        fail("Cannot find the Windows system directory", length ? ERROR_FILENAME_EXCED_RANGE : GetLastError(),
             EXIT_INTERNAL);
    }
    if (system_path[length - 1] != L'\\' && !append(system_path, &length, L"\\")) {
        fail("System directory exceeds the launcher limit", ERROR_FILENAME_EXCED_RANGE, EXIT_INTERNAL);
    }
    first = runtime_available(L"VCRUNTIME140.dll", "VCRUNTIME140.dll", length);
    second = runtime_available(L"VCRUNTIME140_1.dll", "VCRUNTIME140_1.dll", length);
    if (!first || !second) {
        stderr_text("A compatible Microsoft Visual C++ x64 runtime is required.\r\n"
                    "Ask your administrator to install or repair the x64 runtime using Microsoft's guidance:\r\n"
                    "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist\r\n"
                    "Then run this preview again. The preview did not download or install a runtime.\r\n"
                    "Do not bypass a Windows or organization security warning.\r\n");
        ExitProcess(EXIT_PREREQUISITE);
    }
}

static void check_local_path(WCHAR *path) {
    DWORD index, attributes, drive_type;
    WCHAR saved;
    if (!((path[0] >= L'A' && path[0] <= L'Z') || (path[0] >= L'a' && path[0] <= L'z')) ||
        path[1] != L':' || path[2] != L'\\') {
        fail("Use a local drive path without network or device prefixes", ERROR_BAD_PATHNAME, EXIT_USAGE);
    }
    saved = path[3];
    path[3] = L'\0';
    drive_type = GetDriveTypeW(path);
    path[3] = saved;
    if (drive_type != DRIVE_FIXED && drive_type != DRIVE_REMOVABLE && drive_type != DRIVE_RAMDISK) {
        fail("Use a local drive for the complete preview directory", ERROR_BAD_PATHNAME, EXIT_USAGE);
    }
    for (index = 3;; ++index) {
        if (path[index] == L'\\' || path[index] == L'\0') {
            saved = path[index];
            path[index] = L'\0';
            attributes = GetFileAttributesW(path);
            path[index] = saved;
            if (attributes == INVALID_FILE_ATTRIBUTES) {
                fail("Cannot inspect the preview path; extract the complete archive again", GetLastError(), EXIT_INTERNAL);
            }
            if (attributes & FILE_ATTRIBUTE_REPARSE_POINT) {
                fail("Preview paths must not contain links or reparse points", ERROR_REPARSE_TAG_INVALID, EXIT_USAGE);
            }
            if (!saved) {
                if (attributes & FILE_ATTRIBUTE_DIRECTORY) {
                    fail("The preview payload must be a file", ERROR_BAD_PATHNAME, EXIT_INTERNAL);
                }
                return;
            }
            if (!(attributes & FILE_ATTRIBUTE_DIRECTORY)) {
                fail("The preview parent path must be a directory", ERROR_BAD_PATHNAME, EXIT_INTERNAL);
            }
        }
    }
}

static BOOL WINAPI console_control(DWORD event) {
    /* Handlers (unlike the NULL-handler ignore flag) are not inherited.
     * The child receives the same console event and handles graceful shutdown. */
    return event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT;
}

static HANDLE standard_handle(DWORD which, DWORD access) {
    HANDLE original = GetStdHandle(which), duplicate = NULL;
    if (!original || original == INVALID_HANDLE_VALUE) {
        duplicate = CreateFileW(L"NUL", access, FILE_SHARE_READ | FILE_SHARE_WRITE, &inherited,
                                OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (duplicate == INVALID_HANDLE_VALUE) fail("Cannot open a missing standard stream", GetLastError(), EXIT_INTERNAL);
    } else if (!DuplicateHandle(GetCurrentProcess(), original, GetCurrentProcess(), &duplicate,
                                0, TRUE, DUPLICATE_SAME_ACCESS)) {
        fail("Cannot pass a standard stream to the preview", GetLastError(), EXIT_INTERNAL);
    }
    return duplicate;
}

void WINAPI launcher_entry(void) {
    DWORD length, index, directory_length = 0, command_length = 0, status = EXIT_INTERNAL, error;
    WCHAR *tail;
    BOOL quoted = FALSE;
    HANDLE payload;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    check_runtime();
    length = GetModuleFileNameW(NULL, module_path, CAPACITY);
    if (!length || length >= CAPACITY) {
        fail("Cannot locate the preview executable", length ? ERROR_FILENAME_EXCED_RANGE : GetLastError(), EXIT_INTERNAL);
    }
    check_local_path(module_path);
    for (index = 0; index < length; ++index) if (module_path[index] == L'\\') directory_length = index + 1;
    length = directory_length;
    module_path[length] = L'\0';
    if (!append(module_path, &length, L"hbcb-review-preview-runtime.exe")) {
        fail("The preview path exceeds the launcher limit", ERROR_FILENAME_EXCED_RANGE, EXIT_USAGE);
    }
    check_local_path(module_path);
    /* Hold the selected file against writes/deletion until it has been loaded.
     * This is not authentication or protection against the local OS owner. */
    payload = CreateFileW(module_path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                          FILE_ATTRIBUTE_NORMAL, NULL);
    if (payload == INVALID_HANDLE_VALUE) fail("Cannot open the preview payload", GetLastError(), EXIT_INTERNAL);
    tail = GetCommandLineW();
    if (wide_length(tail) >= CAPACITY) fail("Command line exceeds the launcher limit", ERROR_BAD_LENGTH, EXIT_USAGE);
    /* argv[0] has special Windows CRT parsing: double quotes delimit its path;
     * backslashes are literal. Preserve every code unit after it unchanged. */
    while (*tail) {
        if (*tail == L'"') quoted = !quoted;
        else if (!quoted && (*tail == L' ' || *tail == L'\t')) break;
        ++tail;
    }
    if (quoted || !append(command_line, &command_length, L"\"") ||
        !append(command_line, &command_length, module_path) ||
        !append(command_line, &command_length, L"\"") ||
        !append(command_line, &command_length, tail) || command_length >= CAPACITY - 1) {
        fail("Invalid or over-limit preview command line", ERROR_BAD_LENGTH, EXIT_USAGE);
    }
    inherited.nLength = sizeof(inherited);
    inherited.bInheritHandle = TRUE;
    standard_handles[0] = standard_handle(STD_INPUT_HANDLE, GENERIC_READ);
    standard_handles[1] = standard_handle(STD_OUTPUT_HANDLE, GENERIC_WRITE);
    standard_handles[2] = standard_handle(STD_ERROR_HANDLE, GENERIC_WRITE);
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = standard_handles[0];
    startup.StartupInfo.hStdOutput = standard_handles[1];
    startup.StartupInfo.hStdError = standard_handles[2];
    job = CreateJobObjectW(NULL, NULL);
    if (!job) fail("Cannot create the preview process job", GetLastError(), EXIT_INTERNAL);
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) {
        fail("Cannot configure preview process cleanup", GetLastError(), EXIT_INTERNAL);
    }
    InitializeProcThreadAttributeList(NULL, 2, 0, &attribute_bytes);
    if (!attribute_bytes) fail("Cannot size preview process attributes", GetLastError(), EXIT_INTERNAL);
    startup.lpAttributeList = HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, attribute_bytes);
    if (!startup.lpAttributeList) fail("Cannot allocate preview process attributes", ERROR_NOT_ENOUGH_MEMORY, EXIT_INTERNAL);
    if (!InitializeProcThreadAttributeList(startup.lpAttributeList, 2, 0, &attribute_bytes) ||
        !UpdateProcThreadAttribute(startup.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                   standard_handles, sizeof(standard_handles), NULL, NULL) ||
        !UpdateProcThreadAttribute(startup.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST,
                                   &job, sizeof(job), NULL, NULL)) {
        fail("Cannot restrict preview process inheritance", GetLastError(), EXIT_INTERNAL);
    }
    if (!SetConsoleCtrlHandler(console_control, TRUE)) {
        fail("Cannot configure terminal shutdown", GetLastError(), EXIT_INTERNAL);
    }
    /* Atomic job assignment avoids a suspended orphan if the parent is killed
     * between CreateProcess and AssignProcessToJobObject. Windows 10+ only. */
    if (!CreateProcessW(module_path, command_line, NULL, NULL, TRUE,
                        CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT, NULL, NULL,
                        &startup.StartupInfo, &child)) {
        fail("Cannot start the preview payload; extract the complete archive again", GetLastError(), EXIT_INTERNAL);
    }
    CloseHandle(payload);
    DeleteProcThreadAttributeList(startup.lpAttributeList);
    HeapFree(GetProcessHeap(), 0, startup.lpAttributeList);
    for (index = 0; index < 3; ++index) CloseHandle(standard_handles[index]);
    if (ResumeThread(child.hThread) == (DWORD)-1) {
        error = GetLastError();
        TerminateJobObject(job, EXIT_INTERNAL);
        WaitForSingleObject(child.hProcess, INFINITE);
        fail("Cannot resume the preview payload", error, EXIT_INTERNAL);
    }
    CloseHandle(child.hThread);
    if (WaitForSingleObject(child.hProcess, INFINITE) != WAIT_OBJECT_0 || !GetExitCodeProcess(child.hProcess, &status)) {
        error = GetLastError();
        TerminateJobObject(job, EXIT_INTERNAL);
        WaitForSingleObject(child.hProcess, INFINITE);
        fail("Cannot collect the preview exit status", error, EXIT_INTERNAL);
    }
    CloseHandle(child.hProcess);
    CloseHandle(job); /* Also stops any remaining descendants of this launch. */
    ExitProcess(status);
}
