package com.ictstorm.timeguard

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Talks to Jarvis on the Pi (/api/guard/...). Keeps the last status so it works offline. */
object Jarvis {
    // Built-in list, replaced by what Jarvis sends.
    val DEFAULT_APPS = mapOf(
        "com.whatsapp" to "whatsapp", "com.whatsapp.w4b" to "whatsapp",
        "com.instagram.android" to "instagram", "com.instagram.barcelona" to "instagram",
        "com.zhiliaoapp.musically" to "tiktok", "com.ss.android.ugc.trill" to "tiktok",
        "com.snapchat.android" to "snapchat",
        "com.google.android.youtube" to "youtube", "app.revanced.android.youtube" to "youtube",
        "com.reddit.frontpage" to "reddit", "com.twitter.android" to "x", "com.facebook.katana" to "facebook"
    )
    val NAMES = mapOf(
        "whatsapp" to "WhatsApp", "instagram" to "Instagram", "tiktok" to "TikTok", "snapchat" to "Snapchat",
        "youtube" to "YouTube", "reddit" to "Reddit", "x" to "X", "facebook" to "Facebook",
        "instagram_dm" to "Instagram-berichten"
    )

    @Volatile var packages: Map<String, String> = DEFAULT_APPS
    @Volatile var grants: Map<String, Double> = emptyMap()   // app -> unlocked until (epoch seconds)
    @Volatile var enabled = true
    @Volatile var remainingMin = -1.0
    @Volatile var limitMin = 120
    @Volatile var lastOk = 0L
    @Volatile var lastError = ""
    @Volatile var offset = 0.0          // Jarvis clock minus phone clock (seconds)

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("timeguard", Context.MODE_PRIVATE)
    fun url(ctx: Context) = prefs(ctx).getString("url", "http://192.168.0.249:8790")!!.trimEnd('/')
    fun key(ctx: Context) = prefs(ctx).getString("key", "")!!
    fun save(ctx: Context, url: String, key: String) =
        prefs(ctx).edit().putString("url", url.trim()).putString("key", key.trim()).apply()

    fun isOpen(app: String): Boolean {
        if (!enabled) return true
        val now = System.currentTimeMillis() / 1000.0 + offset
        return (grants[app] ?: 0.0) > now || (grants["all"] ?: 0.0) > now
    }

    fun secondsLeft(app: String): Long {
        val now = System.currentTimeMillis() / 1000.0 + offset
        return (maxOf(grants[app] ?: 0.0, grants["all"] ?: 0.0) - now).toLong().coerceAtLeast(0)
    }

    private fun call(ctx: Context, method: String, path: String, body: JSONObject? = null): JSONObject {
        val c = URL(url(ctx) + path).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 5000
        c.readTimeout = 8000
        c.setRequestProperty("X-Jarvis-Key", key(ctx))
        if (body != null) {
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(body.toString().toByteArray()) }
        }
        val code = c.responseCode
        if (code == 401) throw Exception("Verkeerde Jarvis key")
        if (code != 200) throw Exception("Jarvis gaf HTTP $code")
        return JSONObject(c.inputStream.bufferedReader().readText())
    }

    private fun apply(ctx: Context, s: JSONObject) {
        enabled = s.optBoolean("enabled", true)
        if (s.has("now")) offset = s.optDouble("now") - System.currentTimeMillis() / 1000.0
        remainingMin = s.optDouble("remaining_min", -1.0)
        limitMin = s.optInt("limit_min", 120)
        val g = s.optJSONObject("grants") ?: JSONObject()
        grants = g.keys().asSequence().associateWith { g.getDouble(it) }
        s.optJSONObject("apps")?.let { apps ->
            val map = HashMap<String, String>()
            for (id in apps.keys()) {
                val pk = apps.getJSONObject(id).optJSONArray("android") ?: JSONArray()
                for (i in 0 until pk.length()) map[pk.getString(i)] = id
            }
            if (map.isNotEmpty()) packages = map
        }
        lastOk = System.currentTimeMillis()
        lastError = ""
        prefs(ctx).edit().putString("last_status", s.toString()).apply()
    }

    fun loadCached(ctx: Context) {
        prefs(ctx).getString("last_status", null)?.let { runCatching { apply(ctx, JSONObject(it)) } }
        lastOk = 0
    }

    fun refresh(ctx: Context): Boolean = try {
        apply(ctx, call(ctx, "GET", "/api/guard/status?device=pixel"))
        true
    } catch (e: Exception) {
        lastError = e.message ?: "Jarvis niet bereikbaar"
        false
    }

    /** usage: (app, shorts) -> seconds */
    fun report(ctx: Context, usage: Map<Pair<String, Boolean>, Double>): Boolean = try {
        val items = JSONArray()
        for ((k, sec) in usage) items.put(JSONObject().put("app", k.first).put("shorts", k.second).put("seconds", sec))
        apply(ctx, call(ctx, "POST", "/api/guard/usage", JSONObject().put("device", "pixel").put("items", items)))
        true
    } catch (e: Exception) {
        lastError = e.message ?: "Jarvis niet bereikbaar"
        false
    }
}
