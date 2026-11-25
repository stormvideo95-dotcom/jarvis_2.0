package com.ictstorm.timeguard

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/** Tiny helpers so the screens stay code-only (dark, amber, like the Jarvis page). */
object Ui {
    const val BG = 0xFF0B0D12.toInt()
    const val CARD = 0xFF151924.toInt()
    const val LINE = 0xFF262C3B.toInt()
    const val TEXT = 0xFFE8EBF2.toInt()
    const val MUTED = 0xFF8B93A7.toInt()
    const val ACCENT = 0xFFFFB020.toInt()

    fun dp(ctx: Context, v: Int) = (v * ctx.resources.displayMetrics.density).toInt()

    fun column(ctx: Context) = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        setBackgroundColor(BG)
        setPadding(dp(ctx, 24), dp(ctx, 48), dp(ctx, 24), dp(ctx, 24))
    }

    fun text(ctx: Context, s: String, size: Float = 16f, color: Int = TEXT, bold: Boolean = false) = TextView(ctx).apply {
        text = s; textSize = size; setTextColor(color)
        if (bold) typeface = Typeface.DEFAULT_BOLD
        setPadding(0, dp(ctx, 6), 0, dp(ctx, 6))
    }

    fun field(ctx: Context, hint: String, value: String) = EditText(ctx).apply {
        setText(value); this.hint = hint; setTextColor(TEXT); setHintTextColor(MUTED)
        background = GradientDrawable().apply { setColor(CARD); cornerRadius = dp(ctx, 12).toFloat(); setStroke(dp(ctx, 1), LINE) }
        setPadding(dp(ctx, 14), dp(ctx, 12), dp(ctx, 14), dp(ctx, 12))
        isSingleLine = true
    }

    fun button(ctx: Context, s: String, primary: Boolean = true, onClick: () -> Unit) = Button(ctx).apply {
        text = s; isAllCaps = false; textSize = 16f
        setTextColor(if (primary) 0xFF1B1200.toInt() else TEXT)
        background = GradientDrawable().apply { setColor(if (primary) ACCENT else LINE); cornerRadius = dp(ctx, 14).toFloat() }
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            .apply { topMargin = dp(ctx, 12) }
    }

    fun lock(ctx: Context) = TextView(ctx).apply {
        text = "🔒"; textSize = 44f; gravity = Gravity.CENTER
        background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setStroke(dp(ctx, 3), ACCENT); setColor(Color.TRANSPARENT) }
        layoutParams = LinearLayout.LayoutParams(dp(ctx, 110), dp(ctx, 110)).apply { gravity = Gravity.CENTER_HORIZONTAL; bottomMargin = dp(ctx, 18) }
    }

    fun minutes(m: Double): String {
        val v = m.toInt()
        return if (v >= 60) "${v / 60} uur" + (if (v % 60 > 0) " ${v % 60} min" else "") else "$v min"
    }
}
