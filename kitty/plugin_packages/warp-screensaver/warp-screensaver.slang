#language slang 2026
// Hyperspace starfield shown while the user is idle, from the warp-screensaver kitty plugin

import kitty_custom_shader_types;

static const int LAYERS = 4;
static const float STOP_AFTER_SECONDS = 900.0f;
static const float FADE_SECONDS = 2.5f;

float
hash12(float2 p) {
    float3 p3 = frac(float3(p.xyx) * 0.1031f);
    p3 += dot(p3, p3.yzx + 33.33f);
    return frac((p3.x + p3.y) * p3.z);
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float idle = t.animation_progress * STOP_AFTER_SECONDS;
    if (idle <= 0.0f) return color;
    float fade = saturate(idle / FADE_SECONDS) * saturate((STOP_AFTER_SECONDS - idle) / FADE_SECONDS);
    float2 px = float2(d.viewport_size_pixels);
    float2 uv = (t.pos - 0.5f) * float2(px.x / px.y, 1.0f);
    float angle = atan2(uv.y, uv.x);
    float radius = length(uv);
    float time = d.wrapped_time(3600u);
    float3 stars = float3(0.0f);
    [ForceUnroll]
    for (int i = 0; i < LAYERS; i++) {
        float layer = float(i);
        float slices = 90.0f + layer * 50.0f;
        float a = floor((angle + 3.14159f) / 6.28318f * slices);
        float seed = hash12(float2(a, layer));
        if (seed < 0.55f) continue; // most slices are empty space
        float speed = 0.35f + seed * 0.9f;
        float head = frac(seed * 7.0f + time * speed * 0.25f);
        float pos = head * head * 1.2f;
        float streak = 0.02f + 0.18f * head;
        float on = smoothstep(pos - streak, pos, radius) * (1.0f - smoothstep(pos, pos + 0.004f, radius));
        float center = abs(frac((angle + 3.14159f) / 6.28318f * slices) - 0.5f);
        on *= smoothstep(0.5f, 0.05f, center);
        stars += lerp(float3(0.55f, 0.7f, 1.0f), float3(1.0f), seed) * on * (0.4f + head);
    }
    float3 space = float3(0.0f, 0.005f, 0.02f) + stars;
    float3 dimmed = color.rgb * 0.25f;
    return float4(lerp(color.rgb, dimmed + space, fade), 1.0f);
}
