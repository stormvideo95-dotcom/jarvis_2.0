package com.ictstorm.jarvisschool

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Talks to Jarvis on the Pi (/api/school/...). */
object Api {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis_school", Context.MODE_PRIVATE)
    fun url(ctx: Context) = prefs(ctx).getString("url", "http://192.168.0.249:8790")!!.trimEnd('/')
    fun key(ctx: Context) = prefs(ctx).getString("key", "")!!
    fun save(ctx: Context, url: String, key: String) =
        prefs(ctx).edit().putString("url", url.trim()).putString("key", key.trim()).apply()
    fun hasKey(ctx: Context) = key(ctx).isNotEmpty()

    private fun call(ctx: Context, method: String, path: String, body: String? = null, readMs: Int = 30000): String {
        val c = URL(url(ctx) + path).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 6000
        c.readTimeout = readMs
        c.setRequestProperty("X-Jarvis-Key", key(ctx))
        if (body != null) {
            val bytes = body.toByteArray()
            c.doOutput = true
            c.setFixedLengthStreamingMode(bytes.size)
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(bytes) }
        }
        val code = c.responseCode
        if (code == 401) throw Exception("Verkeerde Jarvis key (zie ⚙)")
        if (code != 200) {
            val err = runCatching { c.errorStream?.bufferedReader()?.readText() }.getOrNull() ?: ""
            throw Exception("Jarvis gaf HTTP $code ${err.take(120)}")
        }
        return c.inputStream.bufferedReader().readText()
    }

    fun state(ctx: Context) = JSONObject(call(ctx, "GET", "/api/school/state"))

    fun history(ctx: Context, after: String): JSONArray =
        JSONArray(call(ctx, "GET", "/api/school/chat?after=" + URLEncoder.encode(after, "UTF-8")))

    fun send(ctx: Context, text: String): JSONObject =
        JSONObject(call(ctx, "POST", "/api/school/chat", JSONObject().put("text", text).toString(), readMs = 90000))

    /** Link to a PDF that only lives on the Pi (when Drive is not linked). */
    fun fileUrl(ctx: Context, week: Int, name: String) = url(ctx) + "/api/school/file?week=$week&name=" +
        URLEncoder.encode(name, "UTF-8") + "&key=" + URLEncoder.encode(key(ctx), "UTF-8")

    fun upload(ctx: Context, kind: String, week: Int, pdf: Uri, pages: List<Uri>): JSONObject {
        val pdfBytes = ctx.contentResolver.openInputStream(pdf)!!.use { it.readBytes() }
        val imgs = JSONArray()
        for (p in pages.take(12)) imgs.put(smallJpeg(ctx, p))
        val body = JSONObject()
            .put("kind", kind).put("week", week)
            .put("pdf", Base64.encodeToString(pdfBytes, Base64.NO_WRAP))
            .put("pages", imgs)
        return JSONObject(call(ctx, "POST", "/api/school/upload", body.toString(), readMs = 120000))
    }

    /** Page photo small enough for the AI that reads it (under ~170 KB). */
    private fun smallJpeg(ctx: Context, uri: Uri): String {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        ctx.contentResolver.openInputStream(uri)!!.use { BitmapFactory.decodeStream(it, null, bounds) }
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= 1400) sample *= 2
        val opts = BitmapFactory.Options().apply { inSampleSize = sample }
        var bmp = ctx.contentResolver.openInputStream(uri)!!.use { BitmapFactory.decodeStream(it, null, opts) }!!
        var long = maxOf(bmp.width, bmp.height)
        if (long > 1400) {
            val f = 1400f / long
            bmp = Bitmap.createScaledBitmap(bmp, (bmp.width * f).toInt(), (bmp.height * f).toInt(), true)
        }
        var quality = 70
        while (true) {
            val out = ByteArrayOutputStream()
            bmp.compress(Bitmap.CompressFormat.JPEG, quality, out)
            if (out.size() <= 170_000 || quality <= 30) {
                if (out.size() > 170_000 && maxOf(bmp.width, bmp.height) > 900) {
                    long = maxOf(bmp.width, bmp.height)
                    val f = 900f / long
                    bmp = Bitmap.createScaledBitmap(bmp, (bmp.width * f).toInt(), (bmp.height * f).toInt(), true)
                    quality = 60
                    continue
                }
                return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
            }
            quality -= 10
        }
    }
}
