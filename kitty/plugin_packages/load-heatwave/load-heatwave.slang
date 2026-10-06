#language slang 2026
// Heat shimmer rising from the bottom of the screen, driven by the load-heatwave kitty plugin

import kitty_custom_shader_types;

static const int PLUGIN_CHANNEL = 0;

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float load = d.plugin_params[PLUGIN_CHANNEL * 2].x;
    float heat = saturate((load - 0.5f) / 1.0f);
    if (heat <= 0.0f) return color;
    float2 uv = t.pos;
    float height = 0.15f + 0.35f * heat;
    if (uv.y >= height) return color;
    float time = d.wrapped_time(600u);
    float zone = smoothstep(height, 0.0f, uv.y);
    float wobble = sin(uv.y * 90.0f - time * 6.0f) * 0.5f + sin(uv.y * 37.0f + uv.x * 20.0f - time * 3.7f) * 0.5f;
    float2 offset = float2(wobble * 0.0025f * zone * heat, 0.0f);
    float3 rgb = t.backbuffer.Sample(uv + offset).rgb;
    float3 glow = lerp(float3(1.0f, 0.45f, 0.05f), float3(1.0f, 0.05f, 0.02f), heat);
    float flicker = 0.85f + 0.15f * sin(time * 9.0f + uv.x * 13.0f);
    rgb += glow * zone * zone * 0.35f * heat * flicker;
    return float4(rgb, color.a);
}
