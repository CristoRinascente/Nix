#version 330

uniform vec2 resolution;
uniform vec2 tagPos;      // centro della forma (px, y verso il basso)
uniform float tagW;       // larghezza attuale
uniform float tagH;       // altezza attuale (pallina = diametro)
uniform float tagA;       // opacita' generale
uniform vec3 tagCol;      // colore del tag
uniform float tagKind;    // 0 = done, 1 = notunderstand, 2 = rest
uniform float expandF;    // 0 = pallina piena, 1 = pillola
uniform float sym;        // 0..1 simbolo "scritto"
uniform float textAmt;    // 0..1 flip del testo
uniform vec2 texSize;     // dimensione della texture del testo
uniform sampler2D textTex;

out vec4 finalColor;

const float BASEH = 18.0;

float sdRoundBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

float sdSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}

float sdTriangle(vec2 p, float r) {
    const float k = 1.7320508;
    p.x = abs(p.x) - r;
    p.y = p.y + r / k;
    if (p.x + k * p.y > 0.0) p = vec2(p.x - k * p.y, -k * p.x - p.y) * 0.5;
    p.x -= clamp(p.x, -2.0 * r, 0.0);
    return -length(p) * sign(p.y);
}

void main() {
    vec2 p = vec2(gl_FragCoord.x, resolution.y - gl_FragCoord.y);
    vec2 rel = p - tagPos;
    float hh = tagH * 0.5;
    vec2 hb = vec2(tagW * 0.5, hh);
    float sd = sdRoundBox(rel, hb, hh);
    float body = 1.0 - smoothstep(-1.0, 1.0, sd);

    // riempimento: pallina piena -> vetro chiaro tinteggiato
    float fillMix = smoothstep(0.0, 1.0, expandF);
    float yN = clamp(rel.y / max(hh, 1.0) * 0.5 + 0.5, 0.0, 1.0);
    vec3 glassTop = mix(vec3(1.0), tagCol, 0.10);
    vec3 glassBot = mix(vec3(1.0), tagCol, 0.30);
    vec3 col = mix(tagCol, mix(glassTop, glassBot, yN), fillMix);

    // riflesso glossy nella meta' alta
    float inset = sdRoundBox(rel - vec2(0.0, -hh * 0.38),
                             vec2(max(tagW * 0.5 - 4.0, hh * 0.5), hh * 0.52), hh * 0.5);
    float gloss = (1.0 - smoothstep(-1.0, 1.0, inset)) * mix(0.28, 0.70, fillMix);
    col = mix(col, vec3(1.0), gloss);

    // bordo sottile
    float rim = 1.0 - smoothstep(0.2, 1.6, abs(sd + 0.9));
    col = mix(col, tagCol, rim);

    // icona a sinistra: cerchio pieno (done, rest) o triangolo (alert)
    vec2 iconC = vec2(tagPos.x - tagW * 0.5 + hh, tagPos.y);
    vec2 q = p - iconC;
    float iconR = max(hh - 4.0 * fillMix, 1.0);
    float iconM;
    if (tagKind > 0.5 && tagKind < 1.5) {
        float sdT = sdTriangle(vec2(q.x, -q.y), iconR * 0.96 - 2.5) - 2.5;
        iconM = (1.0 - smoothstep(-0.8, 0.8, sdT)) * smoothstep(0.0, 0.6, expandF);
    } else {
        iconM = 1.0 - smoothstep(-0.8, 0.8, length(q) - iconR);
    }
    col = mix(col, tagCol, iconM);

    // simbolo bianco "scritto" a tratti
    float symS = max(hh / BASEH, 0.2);
    vec2 qs = q / symS;
    float sdS = 100.0;
    if (tagKind < 0.5) {
        // spunta
        vec2 a = vec2(-6.0, 0.5);
        vec2 b = vec2(-1.8, 4.8);
        vec2 c = vec2(6.8, -4.6);
        float fa = clamp(sym * 2.0, 0.0, 1.0);
        float fb = clamp(sym * 2.0 - 1.0, 0.0, 1.0);
        float s1 = sdSeg(qs, a, mix(a, b, max(fa, 0.001)));
        float s2 = sdSeg(qs, b, mix(b, c, max(fb, 0.001))) + ((fb < 0.001) ? 10.0 : 0.0);
        sdS = min(s1, s2) - 1.5;
    } else if (tagKind < 1.5) {
        // punto esclamativo
        float fl = clamp(sym * 1.7, 0.0, 1.0);
        float sl = sdSeg(qs, vec2(0.0, -6.5), vec2(0.0, mix(-6.5, 0.8, max(fl, 0.001)))) - 1.4;
        float sdot = length(qs - vec2(0.0, 5.0)) - 1.8 * smoothstep(0.7, 1.0, sym);
        sdot += (sym < 0.72) ? 10.0 : 0.0;
        sdS = min(sl, sdot);
    } else {
        // tre puntini
        float dm = 100.0;
        for (int i = 0; i < 3; i++) {
            float fi = float(i);
            float r = 2.1 * smoothstep(fi * 0.25, fi * 0.25 + 0.3, sym);
            float dd = length(qs - vec2((fi - 1.0) * 6.5, 0.5)) - r;
            dd += (r < 0.05) ? 10.0 : 0.0;
            dm = min(dm, dd);
        }
        sdS = dm;
    }
    float symM = (1.0 - smoothstep(-0.7, 0.7, sdS)) * smoothstep(0.0, 0.04, sym);
    col = mix(col, vec3(1.0), symM);

    // testo con flip 3D
    float f = cos((1.0 - clamp(textAmt, 0.0, 1.0)) * 1.5708);
    float fl2 = max(f, 0.03);
    float textLeft = tagPos.x - tagW * 0.5 + 40.0;
    vec2 tp = vec2(p.x - textLeft, (p.y - tagPos.y) / fl2 + texSize.y * 0.5);
    vec2 uvT = vec2(tp.x / texSize.x, 1.0 - tp.y / texSize.y);
    float inT = step(0.0, uvT.x) * step(uvT.x, 1.0) * step(0.0, uvT.y) * step(uvT.y, 1.0);
    float cov = texture(textTex, uvT).r * inT * f * step(0.001, textAmt);
    cov *= 1.0 - smoothstep(-6.0, -3.0, sd);
    col = mix(col, tagCol * mix(0.75, 1.0, f), cov);

    // composizione (colore premoltiplicato) con ombra morbida
    float bodyA = body * mix(1.0, 0.96, fillMix);
    float sdSh = sdRoundBox(rel - vec2(0.0, 4.0), hb, hh);
    float shA = exp(-max(sdSh, 0.0) * 0.28) * 0.20 * (1.0 - body);
    vec4 outc = vec4(col * bodyA, bodyA);
    outc += vec4(vec3(0.08, 0.06, 0.14) * shA, shA) * (1.0 - bodyA);
    finalColor = outc * tagA;
}