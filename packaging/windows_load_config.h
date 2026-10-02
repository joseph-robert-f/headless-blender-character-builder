/* SPDX-License-Identifier: GPL-3.0-or-later
 * The CRT normally supplies this PE metadata. Define only the Windows SDK
 * structure here so /DEPENDENTLOADFLAG works without linking CRT code.
 * The linker fills DependentLoadFlags. Other fields deliberately remain zero:
 * this source does not claim CFG instrumentation or supply a security cookie.
 */
#ifndef HBCB_WINDOWS_LOAD_CONFIG_H
#define HBCB_WINDOWS_LOAD_CONFIG_H
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>
#ifndef _WIN64
#error This load configuration requires native x64 compilation.
#endif
const IMAGE_LOAD_CONFIG_DIRECTORY64 _load_config_used = {sizeof(IMAGE_LOAD_CONFIG_DIRECTORY64)};
#endif
