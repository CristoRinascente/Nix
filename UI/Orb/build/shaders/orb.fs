#version 330

uniform vec2 resolution;
uniform vec2 orbCenter;  // centro dell'orb in pixel (y verso l'alto)
uniform float time;
uniform vec2 look;       // direzione dello sguardo, da -1 a 1
uniform float blink;     // 0 = occhi aperti, 1 = chiusi
uniform float bob;       // fluttuazione verticale (in raggi)
uniform float eyeSizeL;  // dimensione occhio sinistro
uniform float eyeSizeR;  // dimensione occhio destro
uniform float shake;     // vibrazione orizzontale (in raggi)
uniform float red;       // 0..1 flash rosso
uniform float check;     // 0..1 disegno della spunta
uniform float scale;     // dimensione della sfera
uniform float eyeOpen;   // 0..1 apparizione degli occhi
uniform float dropY;     // altezza della goccia (0 = centro)
uniform float dropTail;  // coda della goccia (+ sopra, - sotto)
uniform float dropA;     // opacita' della goccia
uniform float ring;      // 0..1 onda all'impatto, negativo = spenta

out vec4 finalColor;

const float R = 70.0;

float sdCapsule(vec2 p, float h, float r) {
    p.y -= clamp(p.y, -h, h);
    return length(p) - r;
}

float sdSegment(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}

float smin(float a, float b, float k) {
    float h = max(k - abs(a - b), 0.0) / k;
    return min(a, b) - h * h * k * 0.25;
}

void main() {
    vec2 center = orbCenter;
    vec2 uv = (gl_FragCoord.xy - center) / R;
    float aa = 1.5 / R;

    float sc = max(scale, 0.001);
    float aaS = aa / sc;
    vec2 s = (uv - vec2(shake, bob)) / sc;
    float d = length(s);
    float sphere = (1.0 - smoothstep(1.0 - aaS, 1.0, d)) * step(0.01, scale);

    // gradiente ciano (basso) -> viola (alto)
    float z = sqrt(max(1.0 - d * d, 0.0));
    vec3 n = vec3(s, z);
    vec3 cyan = vec3(0.30, 0.88, 1.00);
    vec3 violet = vec3(0.42, 0.24, 0.95);
    vec3 col = mix(cyan, violet, smoothstep(-0.8, 0.9, s.y));

    // luce morbida e bagliore interno
    float diff = dot(n, normalize(vec3(-0.35, 0.55, 0.75))) * 0.5 + 0.5;
    col *= 0.78 + 0.30 * diff;
    vec2 c0 = s - vec2(0.0, -0.25);
    col += vec3(0.55, 0.75, 1.0) * exp(-dot(c0, c0) * 2.2) * 0.22;
    col += vec3(0.70, 0.60, 1.0) * pow(1.0 - z, 3.0) * 0.25;

    // plasma interno leggero
    float pl = sin(s.x * 3.2 + time * 0.7 + sin(s.y * 2.6 - time * 0.5) * 1.6) * 0.5 + 0.5;
    col += (pl - 0.5) * 0.10 * vec3(0.5, 0.6, 1.0);

    // successo: leggero aumento di luce
    col *= 1.0 + 0.10 * check;

    // errore: flash rosso
    vec3 redCol = vec3(1.0, 0.10, 0.14);
    col = mix(col, redCol, red * 0.85);

    // occhi
    vec2 lk = look * (1.0 - 0.8 * check);
    vec2 e = s - lk * vec2(0.12, 0.08) - vec2(0.0, 0.06);
    float sq = max(1.0 - blink, 0.06) * (0.3 + 0.7 * eyeOpen);
    float eyes = 0.0;
    float glow = 0.0;

    // occhio sinistro: capsula
    {
        vec2 p = e - vec2(-0.30, 0.0);
        p.y /= sq;
        float sd = sdCapsule(p, 0.12 * eyeSizeL, 0.085 * eyeSizeL);
        eyes = max(eyes, 1.0 - smoothstep(-aaS, aaS, sd));
        glow += exp(-max(sd, 0.0) * 10.0) * 0.18;
    }

    // occhio destro: capsula che diventa spunta
    {
        vec2 p = e - vec2(0.30, 0.0);

        float keep = 1.0 - smoothstep(0.0, 0.3, check);
        float sdC = sdCapsule(vec2(p.x, p.y / sq), 0.12 * eyeSizeR, 0.085 * eyeSizeR);
        eyes = max(eyes, (1.0 - smoothstep(-aaS, aaS, sdC)) * keep);
        glow += exp(-max(sdC, 0.0) * 10.0) * 0.18 * keep;

        vec2 a = vec2(-0.10, -0.01);
        vec2 b = vec2(-0.03, -0.10);
        vec2 c = vec2( 0.12,  0.11);
        float fa = clamp(check * 2.0, 0.0, 1.0);
        float fb = clamp(check * 2.0 - 1.0, 0.0, 1.0);
        float sd1 = sdSegment(p, a, mix(a, b, max(fa, 0.001))) - 0.04;
        float sd2 = sdSegment(p, b, mix(b, c, max(fb, 0.001))) - 0.04;
        sd2 += (fb < 0.001) ? 10.0 : 0.0;
        float sdK = min(sd1, sd2);
        float on = smoothstep(0.0, 0.05, check);
        eyes = max(eyes, (1.0 - smoothstep(-aaS, aaS, sdK)) * on);
        glow += exp(-max(sdK, 0.0) * 10.0) * 0.18 * on;
    }

    eyes *= eyeOpen;
    glow *= eyeOpen;
    col += vec3(0.8, 0.9, 1.0) * glow * 0.5;
    col = mix(col, vec3(1.0), eyes);

    // ombra di contatto
    float shScale = smoothstep(0.35, 1.0, scale);
    vec2 sp = vec2((uv.x - shake) / (0.85 * max(scale, 0.2)), (uv.y + 1.22) / 0.15);
    float shadow = exp(-dot(sp, sp) * 1.6) * (0.32 - bob * 2.0) * shScale;
    vec3 shCol = mix(vec3(0.10, 0.05, 0.20), vec3(0.60, 0.0, 0.05), red);

    // alone rosso durante l'errore
    float halo = exp(-max(d - 1.0, 0.0) * 7.0) * red * 0.55;

    // goccia (teardrop)
    vec2 dp = uv - vec2(0.0, dropY);
    float c1 = length(dp) - 0.13;
    float c2 = length(dp - vec2(0.0, dropTail)) - 0.055;
    float sdD = smin(c1, c2, 0.18);
    float dropM = (1.0 - smoothstep(-aa, aa, sdD)) * dropA;
    float dropGlow = exp(-max(sdD, 0.0) * 9.0) * 0.25 * dropA;
    float hl = smoothstep(0.08, 0.0, length(dp - vec2(-0.04, 0.04)));
    vec3 dcol = mix(cyan, violet, 0.25) + hl * 0.35;

    // onda all'impatto
    float ringV = 0.0;
    if (ring >= 0.0) {
        float rr = 0.20 + ring * 1.35;
        float th = 0.025 + ring * 0.05;
        float dd = (length(uv) - rr) / th;
        ringV = exp(-dd * dd) * pow(1.0 - ring, 2.0) * 0.5;
    }

    // composizione (colore premoltiplicato)
    vec4 ball = vec4(clamp(col, 0.0, 1.0) * sphere, sphere);
    vec4 under = vec4(shCol * shadow + redCol * halo, shadow + halo);
    under += vec4(clamp(dcol, 0.0, 1.0) * dropM + vec3(0.5, 0.85, 1.0) * dropGlow
                  + vec3(0.55, 0.85, 1.0) * ringV,
                  dropM + dropGlow + ringV);
    vec4 outc = ball + under * (1.0 - sphere);
    outc.a = min(outc.a, 1.0);
    outc.rgb = min(outc.rgb, vec3(outc.a));
    finalColor = outc;
}