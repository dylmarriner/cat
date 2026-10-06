#language slang 2026
// Hazard stripes around the active window, driven by the prod-guard kitty plugin

import kitty_custom_shader_types;

static const int PLUGIN_CHANNEL = 0;
static const float BORDER_PX = 6.0f;
static const float STRIPE_PX = 14.0f;

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float4 p = d.plugin_params[PLUGIN_CHANNEL * 2];
    float4 g = d.active_window_geometry;
    if (p.x <= 0.0f || g.z <= 0.0f) return color;
    float2 px = t.pos * float2(d.viewport_size_pixels);
    float2 lo = g.xy * float2(d.viewport_size_pixels);
    float2 hi = (g.xy + g.zw) * float2(d.viewport_size_pixels);
    float inside_outer = step(lo.x, px.x) * step(px.x, hi.x) * step(lo.y, px.y) * step(px.y, hi.y);
    float inside_inner = step(lo.x + BORDER_PX, px.x) * step(px.x, hi.x - BORDER_PX) * step(lo.y + BORDER_PX, px.y) * step(px.y, hi.y - BORDER_PX);
    float border = inside_outer * (1.0f - inside_inner);
    if (border <= 0.0f) {
        // a faint red wash inside the dangerous window
        return float4(color.rgb + float3(0.04f, 0.0f, 0.0f) * inside_outer * color.a, color.a);
    }
    float stripe = step(0.5f, frac((px.x + px.y) / (2.0f * STRIPE_PX)));
    float3 hazard = lerp(float3(0.9f, 0.05f, 0.02f), float3(0.02f, 0.02f, 0.02f), stripe);
    return float4(hazard, 1.0f);
}
