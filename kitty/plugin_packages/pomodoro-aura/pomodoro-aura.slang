#language slang 2026
// Progress bar and edge aura driven by the pomodoro-aura kitty plugin

import kitty_custom_shader_types;

static const int PLUGIN_CHANNEL = 0;
static const float BAR_HEIGHT_PX = 3.0f;
static const float AURA_WIDTH = 0.06f;

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float4 p = d.plugin_params[PLUGIN_CHANNEL * 2];
    if (p.x <= 0.0f) return color;
    float2 uv = t.pos;
    float edge = min(min(uv.x, 1.0f - uv.x), min(uv.y, 1.0f - uv.y));
    float bar_h = BAR_HEIGHT_PX / float(d.viewport_size_pixels.y);
    float top = d.central_area.y + d.central_area.w;
    bool in_bar = uv.y > top - bar_h && uv.y <= top;
    // most of the screen is untouched, skip all the work there
    if (edge >= AURA_WIDTH && !in_bar) return color;
    float progress = saturate(p.y);
    float3 cool = float3(0.02f, 0.55f, 0.5f);
    float3 warm = float3(1.0f, 0.38f, 0.02f);
    float3 tint = p.x > 1.5f ? float3(0.1f, 0.8f, 0.25f) : lerp(cool, warm, progress * progress);
    float aura_strength = p.x > 1.5f ? 0.18f : 0.08f + 0.22f * progress;
    float aura = smoothstep(AURA_WIDTH, 0.0f, edge) * aura_strength;
    float3 rgb = color.rgb + tint * aura * color.a;
    if (in_bar) {
        float filled = step(uv.x, progress);
        rgb = lerp(rgb, tint * (0.35f + 0.65f * filled), 0.85f);
    }
    return float4(rgb, color.a);
}
