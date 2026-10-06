#language slang 2026
// A comet orbiting the active window border, from the busy-orbit kitty plugin

import kitty_custom_shader_types;

static const int PLUGIN_CHANNEL = 0;
static const float SECONDS_PER_LAP = 2.2f;
static const float TAIL = 0.18f;
static const float WIDTH_PX = 3.0f;

// position along the perimeter in [0, 1) of a pixel on the border
float
perimeter_pos(float2 local, float2 size) {
    float total = 2.0f * (size.x + size.y);
    float2 p = local * size;
    float dl = p.x, dr = size.x - p.x, db = p.y, dt = size.y - p.y;
    float m = min(min(dl, dr), min(db, dt));
    if (m == db) return p.x / total;
    if (m == dr) return (size.x + p.y) / total;
    if (m == dt) return (size.x + size.y + (size.x - p.x)) / total;
    return (2.0f * size.x + size.y + (size.y - p.y)) / total;
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float4 g = d.active_window_geometry;
    if (d.plugin_params[PLUGIN_CHANNEL * 2].x <= 0.0f || g.z <= 0.0f) return color;
    float2 vp = float2(d.viewport_size_pixels);
    float2 size = g.zw * vp;
    float2 local = (t.pos - g.xy) / g.zw;
    float2 p = local * size;
    float dist = min(min(p.x, size.x - p.x), min(p.y, size.y - p.y));
    if (dist < -1.0f || dist > WIDTH_PX * 3.0f) return color;
    float head = frac(d.wrapped_time(3600u) / SECONDS_PER_LAP);
    float behind = frac(head - perimeter_pos(saturate(local), size));
    float tail = smoothstep(TAIL, 0.0f, behind);
    float line = smoothstep(WIDTH_PX * 3.0f, 0.0f, dist);
    float3 comet = lerp(float3(0.1f, 0.6f, 1.0f), float3(0.9f, 0.95f, 1.0f), tail * tail);
    return float4(color.rgb + comet * tail * line * 1.4f, color.a);
}
