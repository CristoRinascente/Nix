#include "raylib.h"
#include "rlgl.h"
#include "net.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>

// Funzioni di Windows dichiarate a mano (per non includere windows.h)
struct WinPoint { long x; long y; };
extern "C" __declspec(dllimport) int   __stdcall GetCursorPos(WinPoint* p);
extern "C" __declspec(dllimport) short __stdcall GetAsyncKeyState(int vKey);

static const int   W = 320, H = 300;
static const float kOrbCY = 130.0f;               // centro dell'orb, in px dall'alto della finestra
static const int   kPort = 50555;

static const float kShowDur    = 1.15f;
static const float kHideDur    = 1.10f;
static const float kErrorDur   = 0.7f;
static const float kSuccessDur = 1.5f;
static const float kRollDur    = 1.2f;
static const float kStareDur   = 1.0f;
static const float kStartScale = 0.145f;          // dimensione della sfera appena nasce dalla goccia

// tag
static const float kTagH      = 36.0f;            // altezza della pillola
static const float kTagY      = 250.0f;           // centro del tag, in px dall'alto
static const float kTagInDur  = 1.10f;
static const float kTagHold   = 2.0f;             // secondi di permanenza
static const float kTagOutDur = 0.80f;
static const int   kTexW = 320, kTexH = 32;       // texture del testo
static const float kFontSize = 18.0f, kFontSpacing = 0.2f;

// ---------------- Utilita' ----------------
static float clamp01(float x) { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }
static float smooth01(float x) { x = clamp01(x); return x * x * (3.0f - 2.0f * x); }
static float easeOutBack(float x) {
    x = clamp01(x);
    const float c1 = 1.2f, c3 = c1 + 1.0f;
    float u = x - 1.0f;
    return 1.0f + c3 * u * u * u + c1 * u * u;
}
static float easeInBack(float x) {
    x = clamp01(x);
    const float c1 = 1.2f, c3 = c1 + 1.0f;
    return c3 * x * x * x - c1 * x * x;
}
static float rnd(float a, float b) { return a + (b - a) * (GetRandomValue(0, 10000) / 10000.0f); }
static float approach(float cur, float target, float rate, float dt) {
    return cur + (target - cur) * (1.0f - expf(-rate * dt));
}
static bool starts(const char* s, const char* p) { return strncmp(s, p, strlen(p)) == 0; }
static bool keyHit(int vk, bool& prev) {
    bool down = (GetAsyncKeyState(vk) & 0x8000) != 0;
    bool hit = down && !prev;
    prev = down;
    return hit;
}
static void copyText(char* dst, size_t cap, const char* src) {
    snprintf(dst, cap, "%s", src);
    size_t n = strlen(dst);
    while (n > 0 && (dst[n - 1] == ' ' || dst[n - 1] == '\n' || dst[n - 1] == '\r')) dst[--n] = 0;
}

// ---------------- Stato dell'orb ----------------
enum State    { HIDDEN, SHOWING, VISIBLE, HIDING };
enum Mode     { MODE_IDLE, MODE_REST, MODE_WORKING };
enum Evt      { EVT_NONE, EVT_ROLL, EVT_STARE };
enum TagState { TAG_NONE, TAG_IN, TAG_HOLD, TAG_OUT };

static State  gState = HIDDEN;
static Mode   gMode = MODE_IDLE;
static Evt    gEvt = EVT_NONE;
static double gStateStart = 0.0, gEvtStart = 0.0;
static bool   gPendingShow = false, gPendingHide = false;
static double gErrorStart = -100.0, gSuccessStart = -100.0;
static float  gTargetX = 0, gTargetY = 0, gCurX = 0, gCurY = 0;  // centro dell'orb in coordinate schermo
static bool   gQuit = false;

// stato del tag
static TagState gTag = TAG_NONE;
static double   gTagStart = 0.0;
static int      gTagKind = 0;                     // 0 done, 1 notunderstand, 2 rest
static char     gTagText[64] = "";
static bool     gTagTextDirty = false;
static float    gTagFullW = 120.0f;               // larghezza della pillola aperta
static bool     gTagPending = false;
static int      gTagPendKind = 0;
static char     gTagPendText[64] = "";
static bool     gHideAfterTag = false;

static const char* const kTextsDone[4] = { "fatto", "done", "ok", "ricevuto" };
static const char* const kTextsNotU[4] = { "riprova", "non ho capito", "come?", "ripeti" };
static const char* const kTextsRest[4] = { "aspetto", "ricevuto", "ok", "attendo" };

static void startTag(int kind, const char* text) {
    gTagKind = kind;
    copyText(gTagText, sizeof(gTagText), text);
    gTagTextDirty = true;
    gTagPending = false;
    gTag = TAG_IN;
    gTagStart = GetTime();
}

// ---------------- Funzioni richiamabili ----------------
void orbShow() {                       // chiamata: la goccia scende e l'orb si espande
    if (gState == HIDDEN) {
        gState = SHOWING;
        gStateStart = GetTime();
        gMode = MODE_IDLE;
        gEvt = EVT_NONE;
    } else if (gState == HIDING) gPendingShow = true;
    gPendingHide = false;
    gHideAfterTag = false;
}
void orbHide() {                       // uscita: l'orb si richiude in una goccia che sale
    if (gState == VISIBLE && gTag != TAG_NONE) {   // prima esce il tag, poi l'orb
        gTagPending = false;
        gHideAfterTag = true;
        if (gTag == TAG_HOLD) { gTag = TAG_OUT; gTagStart = GetTime(); }
        gPendingShow = false;
        return;
    }
    if (gState == VISIBLE) { gState = HIDING; gStateStart = GetTime(); gEvt = EVT_NONE; }
    else if (gState == SHOWING) gPendingHide = true;
    gPendingShow = false;
}
void orbError()   { if (gState == VISIBLE) gErrorStart   = GetTime(); }  // vibra + flash rosso
void orbSuccess() { if (gState == VISIBLE) gSuccessStart = GetTime(); }  // spunta nell'occhio destro
void orbMoveTo(float x, float y)  { gTargetX = gCurX = x; gTargetY = gCurY = y; }  // subito
void orbGlideTo(float x, float y) { gTargetX = x; gTargetY = y; }                  // scivolando

// modalita' (restano attive fino al prossimo richiamo)
void orbIdle()    { gMode = MODE_IDLE; }      // segue il mouse
void orbRest()    { gMode = MODE_REST; }      // attesa comando
void orbWorking() { gMode = MODE_WORKING; }   // esecuzione comando in corso

// eventi singoli
void orbEyeRoll()   { if (gState == VISIBLE && gEvt == EVT_NONE) { gEvt = EVT_ROLL;  gEvtStart = GetTime(); } }
void orbStareDown() { if (gState == VISIBLE && gEvt == EVT_NONE) { gEvt = EVT_STARE; gEvtStart = GetTime(); } }

// tag: kind 0 = done, 1 = notunderstand, 2 = rest; testo vuoto = scelto a caso
void orbTag(int kind, const char* text) {
    if (gState != VISIBLE) return;
    char buf[64];
    buf[0] = 0;
    if (text) copyText(buf, sizeof(buf), text);
    if (buf[0] == 0) {
        const char* const* list = (kind == 0) ? kTextsDone : (kind == 1 ? kTextsNotU : kTextsRest);
        copyText(buf, sizeof(buf), list[GetRandomValue(0, 3)]);
    }
    if (gTag == TAG_NONE) {
        startTag(kind, buf);
    } else {                           // c'e' gia' un tag: esce e poi entra il nuovo
        gTagPending = true;
        gTagPendKind = kind;
        copyText(gTagPendText, sizeof(gTagPendText), buf);
        if (gTag == TAG_HOLD) { gTag = TAG_OUT; gTagStart = GetTime(); }
    }
}

static void advanceTag(double now) {
    if (gTag == TAG_NONE) return;
    float a = (float)(now - gTagStart);
    if (gTag == TAG_IN && a >= kTagInDur) {
        gTagStart = now;
        gTag = (gTagPending || gHideAfterTag) ? TAG_OUT : TAG_HOLD;
    } else if (gTag == TAG_HOLD && a >= kTagHold) {
        gTag = TAG_OUT;
        gTagStart = now;
    } else if (gTag == TAG_OUT && a >= kTagOutDur) {
        gTag = TAG_NONE;
        if (gTagPending) {
            startTag(gTagPendKind, gTagPendText);
        } else if (gHideAfterTag) {
            gHideAfterTag = false;
            orbHide();
        }
    }
}

// ---------------- Animazioni di ingresso / uscita dell'orb ----------------
struct Fx {
    float scale = 1.0f, eyeOpen = 1.0f;
    float dropY = 0.0f, dropTail = 0.0f, dropA = 0.0f;
    float ring = -1.0f;
};

static Fx fxShow(float a) {
    Fx f;
    const float fall = 0.40f;
    if (a < fall) {
        float k = a / fall;
        f.scale = 0.0f;
        f.eyeOpen = 0.0f;
        f.dropY = 1.45f * (1.0f - k * k);
        f.dropTail = 0.30f * sinf(k * PI);
        f.dropA = smooth01(a / 0.08f);
    } else {
        float x = clamp01((a - fall) / 0.60f);
        f.scale = kStartScale + (1.0f - kStartScale) * easeOutBack(x);
        f.eyeOpen = smooth01((a - fall - 0.30f) / 0.30f);
        f.ring = clamp01((a - fall) / 0.75f);
    }
    return f;
}

static Fx fxHide(float a) {
    Fx f;
    f.eyeOpen = 1.0f - smooth01(a / 0.22f);
    const float t0 = 0.15f, t1 = 0.65f;
    if (a < t1) {
        float x = clamp01((a - t0) / (t1 - t0));
        f.scale = 1.0f + (kStartScale - 1.0f) * easeInBack(x);
    } else {
        f.scale = 0.0f;
        f.eyeOpen = 0.0f;
        float k = clamp01((a - t1) / 0.40f);
        f.dropY = 1.50f * k * k;
        f.dropTail = -0.30f * sinf(k * PI);
        f.dropA = 1.0f - smooth01((k - 0.7f) / 0.3f);
    }
    return f;
}

// ---------------- Animazioni del tag ----------------
struct TagFx {
    bool on = false;
    float cy = 0.0f, r = 18.0f, w = 36.0f;
    float expand = 0.0f, sym = 0.0f, textAmt = 0.0f;
};

static TagFx tagIn(float a, float fullW) {
    TagFx t;
    t.on = true;
    float d = clamp01(a / 0.35f);
    float mv = 1.0f - powf(1.0f - d, 3.0f);                     // la pallina scende e rallenta
    t.cy = kOrbCY + (kTagY - kOrbCY) * mv;
    t.r = kTagH * 0.5f * (0.4f + 0.6f * smooth01(a / 0.30f));   // cresce uscendo dall'orb
    t.sym = smooth01((a - 0.30f) / 0.32f);                      // il simbolo si scrive
    t.expand = smooth01((a - 0.55f) / 0.30f);
    float ex = easeOutBack(clamp01((a - 0.55f) / 0.30f));
    t.w = 2.0f * t.r + (fullW - kTagH) * ex;                    // si espande a pillola
    t.textAmt = smooth01((a - 0.80f) / 0.30f);                  // il testo fa il flip
    return t;
}

static TagFx tagHold(float fullW) {
    TagFx t;
    t.on = true;
    t.cy = kTagY;
    t.r = kTagH * 0.5f;
    t.w = fullW;
    t.expand = 1.0f;
    t.sym = 1.0f;
    t.textAmt = 1.0f;
    return t;
}

static TagFx tagOut(float a, float fullW) {
    TagFx t;
    t.on = true;
    t.textAmt = 1.0f - smooth01(a / 0.18f);
    t.expand = 1.0f - smooth01((a - 0.12f) / 0.33f);
    t.sym = 1.0f;
    float mv = clamp01((a - 0.42f) / 0.34f);
    t.cy = kTagY + (kOrbCY - kTagY) * (mv * mv);                // risale accelerando
    t.r = kTagH * 0.5f * (1.0f - 0.6f * smooth01((a - 0.42f) / 0.34f));
    t.w = 2.0f * t.r + (fullW - kTagH) * t.expand;
    return t;
}

static TagFx tagFrame(double now) {
    if (gTag == TAG_NONE) return TagFx();
    float a = (float)(now - gTagStart);
    if (gTag == TAG_IN) return tagIn(a, gTagFullW);
    if (gTag == TAG_OUT) return tagOut(a, gTagFullW);
    return tagHold(gTagFullW);
}

// ---------------- Comportamento degli occhi ----------------
struct EyeState {
    Vector2 gaze = { 0.0f, 0.0f };          // sguardo base (lisciato)
    Vector2 restTarget = { 0.0f, 0.0f };
    float lid = 0.0f, lidTarget = 0.0f;
    float restW = 0.0f, persp = 0.0f;
    float bobPhase = 0.0f, breathPhase = 0.0f, workPhase = 0.0f;
    double nextLook = 0, nextLid = 0, nextBlink = 0, blinkStart = -10.0, nextEvent = 0;
    double nextUp = 0, upUntil = 0;
    Mode lastMode = MODE_IDLE;
};

struct EyeOut {
    Vector2 gaze = { 0.0f, 0.0f };
    float blink = 0.0f, sizeL = 1.0f, sizeR = 1.0f, bob = 0.0f, scaleMul = 1.0f;
};

static EyeOut updateEyes(EyeState& E, Mode mode, Vector2 mouseGaze, float dt, double now) {
    // cambio di modalita': timer nuovi
    if (mode != E.lastMode) {
        E.lastMode = mode;
        E.nextLook = now + 0.4;
        E.nextLid = now + 1.5;
        E.nextBlink = now + 1.5;
        E.nextEvent = now + 15.0 + rnd(-3.0f, 3.0f);   // timer degli eventi speciali nel rest
        E.nextUp = now + 2.0;
        E.upUntil = 0.0;
        E.workPhase = 0.0f;
    }

    // oscillazione sinusoidale (piu' ampia e lenta nel rest) e respiro
    E.restW = approach(E.restW, mode == MODE_REST ? 1.0f : 0.0f, 2.0f, dt);
    E.bobPhase += dt * (1.6f - 0.5f * E.restW);
    E.breathPhase += dt * 1.3f;

    EyeOut o;
    o.bob = sinf(E.bobPhase) * (0.03f + 0.035f * E.restW);
    o.scaleMul = 1.0f + 0.025f * E.restW * sinf(E.breathPhase);

    Vector2 target = mouseGaze;
    float rate = 10.0f;
    float pulse = 0.0f;

    if (mode == MODE_REST) {
        if (now >= E.nextLook) {
            if (GetRandomValue(0, 99) < 30) E.restTarget = { rnd(-0.2f, 0.2f), rnd(-0.1f, 0.1f) };
            else                            E.restTarget = { rnd(-0.9f, 0.9f), rnd(-0.45f, 0.6f) };
            E.nextLook = now + rnd(1.2f, 3.5f);
        }
        if (now >= E.nextLid) {
            E.lidTarget = (GetRandomValue(0, 99) < 45) ? 0.0f : rnd(0.2f, 0.55f);
            E.nextLid = now + rnd(1.5f, 4.5f);
        }
        if (now >= E.nextBlink) {
            E.blinkStart = now;
            E.nextBlink = now + rnd(1.8f, 7.0f);
        }
        if (now >= E.nextEvent) {
            E.nextEvent = now + 15.0 + rnd(-3.0f, 3.0f);
            int r = GetRandomValue(0, 99);
            if (r < 25)      orbEyeRoll();     // 25%
            else if (r < 40) orbStareDown();   // 15%
        }
        target = E.restTarget;
        rate = 6.0f;
        float bp = (float)(now - E.blinkStart);
        pulse = (bp >= 0.0f && bp < 0.16f) ? sinf(bp / 0.16f * PI) : 0.0f;
    } else {
        E.lidTarget = 0.0f;
        float ph = (float)fmod(now, 4.0);
        pulse = (ph < 0.16f) ? sinf(ph / 0.16f * PI) : 0.0f;

        if (mode == MODE_WORKING) {
            E.workPhase += dt * 2.6f;
            float sx = sinf(E.workPhase) * 0.9f;
            float sy = 0.0f;
            if (now >= E.nextUp) {
                if (GetRandomValue(0, 99) < 55) E.upUntil = now + rnd(0.7f, 1.1f);
                E.nextUp = now + rnd(2.5f, 5.5f);
            }
            if (now < E.upUntil) { sy = 0.8f; sx *= 0.3f; }   // ogni tanto guarda in alto
            target = { sx, sy };
            rate = 7.0f;
        }
    }

    E.gaze.x = approach(E.gaze.x, target.x, rate, dt);
    E.gaze.y = approach(E.gaze.y, target.y, rate, dt);
    E.lid = approach(E.lid, E.lidTarget, 8.0f, dt);
    E.persp = approach(E.persp, mode == MODE_WORKING ? 1.0f : 0.0f, 4.0f, dt);

    o.gaze = E.gaze;
    float lidOut = fmaxf(E.lid, pulse);

    // prospettiva: oO guardando a destra, Oo a sinistra
    float gx = fmaxf(-1.0f, fminf(1.0f, E.gaze.x));
    o.sizeL = 1.0f - 0.28f * gx * E.persp;
    o.sizeR = 1.0f + 0.28f * gx * E.persp;

    // eventi singoli
    if (gEvt != EVT_NONE) {
        float dur = (gEvt == EVT_ROLL) ? kRollDur : kStareDur;
        float k = (float)(now - gEvtStart) / dur;
        if (k >= 1.0f) {
            gEvt = EVT_NONE;
        } else if (gEvt == EVT_ROLL) {
            float w = smooth01(k / 0.12f) * smooth01((1.0f - k) / 0.12f);
            float th = PI - 2.0f * PI * smooth01(k);          // un giro completo
            Vector2 evg = { cosf(th) * 0.9f, sinf(th) * 0.8f };
            o.gaze.x += (evg.x - o.gaze.x) * w;
            o.gaze.y += (evg.y - o.gaze.y) * w;
        } else {
            float up = easeOutBack(k / 0.16f);
            float down = 1.0f - smooth01((k - 0.72f) / 0.28f);
            float env = smooth01(k / 0.15f) * down;
            float w = smooth01(k / 0.10f) * (1.0f - smooth01((k - 0.8f) / 0.2f));
            o.gaze.x += (mouseGaze.x - o.gaze.x) * w;         // bloccati sul mouse
            o.gaze.y += (mouseGaze.y - o.gaze.y) * w;
            o.scaleMul *= 1.0f + 0.30f * up * down;           // zoom +30%
            float giant = 1.0f + 0.75f * env;                 // occhi giganti
            o.sizeL *= giant;
            o.sizeR *= giant;
            lidOut *= (1.0f - env);
        }
    }

    o.blink = lidOut;
    return o;
}

// ---------------- Comandi in arrivo da Python ----------------
static void handleCommand(const char* msg) {
    int x, y;
    if (starts(msg, "show")) {
        if (sscanf(msg + 4, "%d %d", &x, &y) == 2) orbMoveTo((float)x, (float)y);
        orbShow();
    } else if (starts(msg, "hide")) {
        orbHide();
    } else if (starts(msg, "error")) {
        orbError();
    } else if (starts(msg, "ok") || starts(msg, "success")) {
        orbSuccess();
    } else if (starts(msg, "move")) {
        if (sscanf(msg + 4, "%d %d", &x, &y) == 2) orbMoveTo((float)x, (float)y);
    } else if (starts(msg, "glide")) {
        if (sscanf(msg + 5, "%d %d", &x, &y) == 2) orbGlideTo((float)x, (float)y);
    } else if (starts(msg, "rest")) {
        orbRest();
    } else if (starts(msg, "working")) {
        orbWorking();
    } else if (starts(msg, "idle")) {
        orbIdle();
    } else if (starts(msg, "eye_roll") || starts(msg, "roll")) {
        orbEyeRoll();
    } else if (starts(msg, "stare")) {
        orbStareDown();
    } else if (starts(msg, "tag")) {
        const char* r = msg + 3;
        while (*r == ' ') r++;
        int kind = -1;
        const char* tx = r;
        if (starts(r, "notunderstand")) { kind = 1; tx = r + 13; }
        else if (starts(r, "done"))     { kind = 0; tx = r + 4; }
        else if (starts(r, "rest"))     { kind = 2; tx = r + 4; }
        if (kind >= 0) {
            while (*tx == ' ') tx++;
            orbTag(kind, tx);
        }
    } else if (starts(msg, "quit")) {
        gQuit = true;
    }
}

int main() {
    SetConfigFlags(FLAG_WINDOW_TRANSPARENT | FLAG_WINDOW_UNDECORATED |
                   FLAG_WINDOW_TOPMOST | FLAG_WINDOW_MOUSE_PASSTHROUGH);
    InitWindow(W, H, "orb");
    SetTargetFPS(60);
    SetRandomSeed((unsigned int)time(nullptr));

    // ----- shader dell'orb -----
    Shader shader = LoadShader(nullptr, "shaders/orb.fs");
    int locRes      = GetShaderLocation(shader, "resolution");
    int locCenter   = GetShaderLocation(shader, "orbCenter");
    int locTime     = GetShaderLocation(shader, "time");
    int locLook     = GetShaderLocation(shader, "look");
    int locBlink    = GetShaderLocation(shader, "blink");
    int locBob      = GetShaderLocation(shader, "bob");
    int locSizeL    = GetShaderLocation(shader, "eyeSizeL");
    int locSizeR    = GetShaderLocation(shader, "eyeSizeR");
    int locShake    = GetShaderLocation(shader, "shake");
    int locRed      = GetShaderLocation(shader, "red");
    int locCheck    = GetShaderLocation(shader, "check");
    int locScale    = GetShaderLocation(shader, "scale");
    int locEyeOpen  = GetShaderLocation(shader, "eyeOpen");
    int locDropY    = GetShaderLocation(shader, "dropY");
    int locDropTail = GetShaderLocation(shader, "dropTail");
    int locDropA    = GetShaderLocation(shader, "dropA");
    int locRing     = GetShaderLocation(shader, "ring");

    float res[2] = { (float)W, (float)H };
    float orbC[2] = { W * 0.5f, H - kOrbCY };          // y verso l'alto (come gl_FragCoord)
    SetShaderValue(shader, locRes, res, SHADER_UNIFORM_VEC2);
    SetShaderValue(shader, locCenter, orbC, SHADER_UNIFORM_VEC2);

    // ----- shader dei tag, font e texture del testo -----
    Shader tagShader = LoadShader(nullptr, "shaders/tag.fs");
    int tRes     = GetShaderLocation(tagShader, "resolution");
    int tPos     = GetShaderLocation(tagShader, "tagPos");
    int tW       = GetShaderLocation(tagShader, "tagW");
    int tH       = GetShaderLocation(tagShader, "tagH");
    int tA       = GetShaderLocation(tagShader, "tagA");
    int tCol     = GetShaderLocation(tagShader, "tagCol");
    int tKind    = GetShaderLocation(tagShader, "tagKind");
    int tExpand  = GetShaderLocation(tagShader, "expandF");
    int tSym     = GetShaderLocation(tagShader, "sym");
    int tTextAmt = GetShaderLocation(tagShader, "textAmt");
    int tTexSize = GetShaderLocation(tagShader, "texSize");
    int tTexLoc  = GetShaderLocation(tagShader, "textTex");

    float texSize[2] = { (float)kTexW, (float)kTexH };
    SetShaderValue(tagShader, tRes, res, SHADER_UNIFORM_VEC2);
    SetShaderValue(tagShader, tTexSize, texSize, SHADER_UNIFORM_VEC2);

    int cps[224];
    for (int i = 0; i < 224; i++) cps[i] = 32 + i;       // caratteri latini con accenti
    Font font = LoadFontEx("assets/InterTight-SemiBold.ttf", (int)kFontSize, cps, 224);
    SetTextureFilter(font.texture, TEXTURE_FILTER_BILINEAR);
    RenderTexture2D textRT = LoadRenderTexture(kTexW, kTexH);
    SetTextureFilter(textRT.texture, TEXTURE_FILTER_BILINEAR);

    static const float kTagCols[3][3] = {
        { 0.063f, 0.725f, 0.506f },   // verde smeraldo
        { 1.000f, 0.550f, 0.120f },   // arancione caldo
        { 0.480f, 0.530f, 0.580f }    // grigio neutro
    };

    Vector2 wp = GetWindowPosition();
    gCurX = gTargetX = wp.x + W * 0.5f;
    gCurY = gTargetY = wp.y + kOrbCY;
    int lastWx = (int)wp.x, lastWy = (int)wp.y;

    if (!netInit(kPort)) TraceLog(LOG_WARNING, "ORB: impossibile aprire la porta UDP %d", kPort);

    EyeState eyes;
    bool prevF6 = false, prevF7 = false, prevF8 = false, prevF9 = false;
    bool blankDrawn = false;
    double last = GetTime();

    while (!gQuit && !WindowShouldClose()) {
        double now = GetTime();
        float dt = (float)(now - last);
        if (dt > 0.05f) dt = 0.05f;
        last = now;

        // tasti di prova (funzionano anche senza focus): F6 chiama, F7 esce, F8 errore, F9 successo
        if (keyHit(0x75, prevF6)) orbShow();
        if (keyHit(0x76, prevF7)) orbHide();
        if (keyHit(0x77, prevF8)) orbError();
        if (keyHit(0x78, prevF9)) orbSuccess();

        // comandi da altri programmi
        char msg[128];
        while (netPoll(msg, sizeof(msg))) handleCommand(msg);

        // posizione (con scivolamento morbido)
        float k = 1.0f - expf(-dt * 9.0f);
        gCurX += (gTargetX - gCurX) * k;
        gCurY += (gTargetY - gCurY) * k;
        if (fabsf(gTargetX - gCurX) < 0.4f) gCurX = gTargetX;
        if (fabsf(gTargetY - gCurY) < 0.4f) gCurY = gTargetY;
        int wx = (int)lroundf(gCurX - W * 0.5f);
        int wy = (int)lroundf(gCurY - kOrbCY);
        if (wx != lastWx || wy != lastWy) {
            SetWindowPosition(wx, wy);
            lastWx = wx;
            lastWy = wy;
        }

        // avanzamento del tag e passaggi di stato dell'orb
        advanceTag(now);
        float age = (float)(now - gStateStart);
        if (gState == SHOWING && age >= kShowDur) {
            gState = VISIBLE;
            gStateStart = now;
            if (gPendingHide) { gPendingHide = false; orbHide(); }
        } else if (gState == HIDING && age >= kHideDur) {
            gState = HIDDEN;
            if (gPendingShow) { gPendingShow = false; orbShow(); }
        }

        // orb nascosto: nessun disegno, quasi zero consumo
        if (gState == HIDDEN) {
            if (!blankDrawn) {
                BeginDrawing();
                ClearBackground(BLANK);
                EndDrawing();
                blankDrawn = true;
            } else {
                PollInputEvents();
                WaitTime(0.016);
            }
            continue;
        }
        blankDrawn = false;

        // nuovo testo del tag: lo disegno nella texture e misuro la pillola
        if (gTagTextDirty) {
            gTagTextDirty = false;
            Vector2 ts = MeasureTextEx(font, gTagText, kFontSize, kFontSpacing);
            gTagFullW = fminf(ts.x + 56.0f, (float)(W - 20));
            BeginTextureMode(textRT);
            ClearBackground(BLANK);
            DrawTextEx(font, gTagText, Vector2{ 0.0f, (kTexH - kFontSize) * 0.5f },
                       kFontSize, kFontSpacing, WHITE);
            EndTextureMode();
        }

        // animazioni di ingresso / uscita dell'orb
        age = (float)(now - gStateStart);
        Fx fx;
        if (gState == SHOWING) fx = fxShow(age);
        else if (gState == HIDING) fx = fxHide(age);

        // direzione del mouse (su tutto lo schermo)
        WinPoint c;
        GetCursorPos(&c);
        Vector2 mg = { (c.x - gCurX) / 300.0f, -(c.y - gCurY) / 300.0f };
        float len = sqrtf(mg.x * mg.x + mg.y * mg.y);
        if (len > 1.0f) { mg.x /= len; mg.y /= len; }

        // comportamento degli occhi
        EyeOut eo = updateEyes(eyes, gMode, mg, dt, now);

        // errore: vibrazione + flash rosso
        float shake = 0.0f, red = 0.0f;
        float ea = (float)(now - gErrorStart);
        if (gState == VISIBLE && ea >= 0.0f && ea < kErrorDur) {
            float q = 1.0f - ea / kErrorDur;
            shake = sinf(ea * 80.0f) * 0.09f * q;
            red = q * q;
        }

        // successo: occhio destro -> spunta
        float check = 0.0f;
        float sa = (float)(now - gSuccessStart);
        if (gState == VISIBLE && sa >= 0.0f && sa < kSuccessDur) {
            if (sa < 0.35f)      check = smooth01(sa / 0.35f);
            else if (sa < 1.25f) check = 1.0f;
            else                 check = 1.0f - smooth01((sa - 1.25f) / 0.25f);
        }

        float blink = eo.blink;
        if (gState != VISIBLE || check > 0.0f || red > 0.0f) blink = 0.0f;
        float t = (float)now;
        float scaleU = fx.scale * eo.scaleMul;

        SetShaderValue(shader, locTime,     &t,            SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locLook,     &eo.gaze,      SHADER_UNIFORM_VEC2);
        SetShaderValue(shader, locBlink,    &blink,        SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locBob,      &eo.bob,       SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locSizeL,    &eo.sizeL,     SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locSizeR,    &eo.sizeR,     SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locShake,    &shake,        SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locRed,      &red,          SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locCheck,    &check,        SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locScale,    &scaleU,       SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locEyeOpen,  &fx.eyeOpen,   SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locDropY,    &fx.dropY,     SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locDropTail, &fx.dropTail,  SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locDropA,    &fx.dropA,     SHADER_UNIFORM_FLOAT);
        SetShaderValue(shader, locRing,     &fx.ring,      SHADER_UNIFORM_FLOAT);

        // tag
        TagFx tf = tagFrame(now);
        if (tf.on) {
            float tagPos[2] = { W * 0.5f, tf.cy };
            float tagH = tf.r * 2.0f;
            float tagAlpha = 1.0f;
            float kindF = (float)gTagKind;
            SetShaderValue(tagShader, tPos,     tagPos,     SHADER_UNIFORM_VEC2);
            SetShaderValue(tagShader, tW,       &tf.w,      SHADER_UNIFORM_FLOAT);
            SetShaderValue(tagShader, tH,       &tagH,      SHADER_UNIFORM_FLOAT);
            SetShaderValue(tagShader, tA,       &tagAlpha,  SHADER_UNIFORM_FLOAT);
            SetShaderValue(tagShader, tCol,     kTagCols[gTagKind], SHADER_UNIFORM_VEC3);
            SetShaderValue(tagShader, tKind,    &kindF,     SHADER_UNIFORM_FLOAT);
            SetShaderValue(tagShader, tExpand,  &tf.expand, SHADER_UNIFORM_FLOAT);
            SetShaderValue(tagShader, tSym,     &tf.sym,    SHADER_UNIFORM_FLOAT);
            SetShaderValue(tagShader, tTextAmt, &tf.textAmt, SHADER_UNIFORM_FLOAT);
        }

        BeginDrawing();
        ClearBackground(BLANK);
        rlSetBlendFactors(RL_ONE, RL_ONE_MINUS_SRC_ALPHA, RL_FUNC_ADD);
        BeginBlendMode(BLEND_CUSTOM);

        if (tf.on) {                                  // il tag sta dietro l'orb
            BeginShaderMode(tagShader);
            SetShaderValueTexture(tagShader, tTexLoc, textRT.texture);
            DrawRectangle(0, 0, W, H, WHITE);
            EndShaderMode();
        }

        BeginShaderMode(shader);                      // orb
        DrawRectangle(0, 0, W, H, WHITE);
        EndShaderMode();

        EndBlendMode();
        EndDrawing();
    }

    UnloadFont(font);
    UnloadRenderTexture(textRT);
    UnloadShader(tagShader);
    UnloadShader(shader);
    netClose();
    CloseWindow();
    return 0;
}