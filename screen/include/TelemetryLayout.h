#pragma once
constexpr int TELEMETRY_PAGES=14;
inline int telemetryRowY(bool portrait,int row){return (portrait?121:100)+row*(portrait?32:16);}
