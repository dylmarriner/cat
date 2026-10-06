#language slang 2026
// Particle bursts launched by the streak-fireworks kitty plugin

import kitty_custom_shader_types;

static const int PLUGIN_CHANNEL = 0;
static const int PARTICLES = 48;
static const int MAX_BURSTS = 5;

float3
hash31(float p) {
    float3 p3 = frac(float3(p) * float3(0.1031f, 0.11369f, 0.13787f));
    p3 += dot(p3, p3.yzx + 19.19f);
    return frac(float3((p3.x + p3.y) * p3.z, (p3.x + p3.z) * p3.y, (p3.y + p3.z) * p3.x));
}

float3
hue(float h) {
    return saturate(abs(frac(h + float3(0.0f, 2.0f / 3.0f, 1.0f / 3.0f)) * 6.0f - 3.0f) - 1.0f);
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float4 p = d.plugin_params[PLUGIN_CHANNEL * 2];
    float progress = t.animation_progress;
    if (p.x <= 0.0f || progress <= 0.0f || progress >= 1.0f) return color;
    float2 px = float2(d.viewport_size_pixels);
    float aspect = px.x / px.y;
    float2 uv = float2(t.pos.x * aspect, t.pos.y);
    float3 glow = float3(0.0f);
    int bursts = clamp(int(p.x), 1, MAX_BURSTS);
    [ForceUnroll]
    for (int b = 0; b < MAX_BURSTS; b++) {
        if (b >= bursts) break;
        float3 seed = hash31(float(b) * 13.0f + p.y * 100.0f);
        float start = float(b) * 0.12f;
        float local = saturate((progress - start) / 0.75f);
        if (local <= 0.0f || local >= 1.0f) continue;
        float2 center = float2((0.2f + 0.6f * seed.x) * aspect, 0.45f + 0.35f * seed.y);
        // particles never travel further than this from the burst center
        float reach = 0.34f * sqrt(local) + 0.12f * local * local + 0.06f;
        if (length(uv - center) > reach) continue;
        float3 base = hue(p.y + seed.z * 0.35f);
        float fade = 1.0f - local;
        [ForceUnroll]
        for (int i = 0; i < PARTICLES; i++) {
            float3 n = hash31(float(i) + seed.x * 57.0f);
            float angle = n.x * 6.2831853f;
            float speed = 0.12f + 0.22f * n.y;
            float2 pos = center + float2(cos(angle), sin(angle)) * speed * sqrt(local) - float2(0.0f, 0.12f * local * local);
            float2 delta = uv - pos;
            float size = 0.0022f * fade;
            float sparkle = 0.6f + 0.4f * sin(local * 40.0f + n.z * 20.0f);
            glow += base * (size * size / max(dot(delta, delta), 1e-6f)) * sparkle * fade;
        }
    }
    float3 rgb = color.rgb + min(glow, float3(3.0f)) * color.a;
    return float4(rgb, color.a);
}
