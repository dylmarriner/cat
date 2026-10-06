#language slang 2026
// Expanding ring of light when the screen-watcher kitty plugin finds a match

import kitty_custom_shader_types;

static const int PLUGIN_CHANNEL = 0;

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float progress = t.animation_progress;
    if (progress <= 0.0f || progress >= 1.0f) return color;
    float2 px = float2(d.viewport_size_pixels);
    float2 uv = (t.pos - 0.5f) * float2(px.x / px.y, 1.0f);
    float radius = progress * 1.2f;
    float ring = smoothstep(0.08f, 0.0f, abs(length(uv) - radius)) * (1.0f - progress);
    float edge = min(min(t.pos.x, 1.0f - t.pos.x), min(t.pos.y, 1.0f - t.pos.y));
    float frame = smoothstep(0.03f, 0.0f, edge) * (1.0f - progress);
    float3 light = float3(0.2f, 0.85f, 1.0f) * (ring * 0.6f + frame);
    return float4(color.rgb + light * color.a, color.a);
}
