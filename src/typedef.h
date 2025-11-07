#pragma once

#define STR_IMPL(x) #x
#define STR(x) STR_IMPL(x)

// tune to cpu cache line size such that uint8 * PADDING = cache line size
// for x86
// constexpr int PADDING = 64;
// for ARM
constexpr int PADDING = 256;

// Select type

//using TypeLongInt = __int128;

//Fall back for ARM
using TypeLongInt = long long;