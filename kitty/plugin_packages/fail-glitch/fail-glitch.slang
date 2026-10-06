#language slang 2026
// RGB split and scanline tearing driven by the fail-glitch kitty plugin

import kitty_custom_shader_types;

static const int PLUGIN_CHANNEL = 0;
static const float MAX_SHIFT = 0.012f;
static const float BANDS = 28.0f;

float
hash1(float n) {
    return frac(sin(n) * 43758.5453f);
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float4 p = d.plugin_params[PLUGIN_CHANNEL * 2];
    float strength = p.x * (1.0f - t.animation_progress);
    if (strength <= 0.001f) return color;
    float2 uv = t.pos;
    float frame = floor(d.wrapped_time(600u) * 30.0f) + p.y;
    float band = floor(uv.y * BANDS);
    float tear = step(0.72f, hash1(band * 3.7f + frame * 1.3f));
    float jitter = (hash1(band * 7.13f + frame) - 0.5f) * 2.0f;
    float2 offset = float2(jitter * tear * MAX_SHIFT * 3.0f * strength, 0.0f);
    float shift = MAX_SHIFT * strength;
    float3 rgb = float3(
        t.backbuffer.Sample(uv + offset + float2(shift, 0.0f)).r, t.backbuffer.Sample(uv + offset).g, t.backbuffer.Sample(uv + offset - float2(shift, 0.0f)).b);
    rgb = lerp(rgb, rgb * float3(1.5f, 0.4f, 0.4f) + float3(0.06f, 0.0f, 0.0f), strength * 0.45f);
    float scan = 0.9f + 0.1f * sin(uv.y * float(d.viewport_size_pixels.y) * 3.14159f);
    rgb *= lerp(1.0f, scan, strength);
    return float4(rgb * color.a, color.a);
}
