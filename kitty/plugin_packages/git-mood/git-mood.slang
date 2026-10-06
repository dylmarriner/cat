#language slang 2026
// Ambient repository state light from the git-mood kitty plugin

import kitty_custom_shader_types;

static const int PLUGIN_CHANNEL = 0;
static const float STRENGTH = 0.22f;

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float4 p = d.plugin_params[PLUGIN_CHANNEL * 2];
    float4 g = d.active_window_geometry;
    if (p.w <= 0.0f || g.z <= 0.0f) return color;
    float2 local = (t.pos - g.xy) / g.zw;
    if (any(local < float2(0.0f)) || any(local > float2(1.0f))) return color;
    // light pools in the bottom right corner of the active window and along its left edge
    float corner = smoothstep(0.55f, 0.0f, length((local - float2(1.0f, 0.0f)) * float2(1.0f, 1.6f)));
    float edge = smoothstep(0.012f, 0.0f, local.x);
    float light = max(corner * STRENGTH, edge * 0.8f);
    return float4(color.rgb + p.rgb * light * color.a, color.a);
}
