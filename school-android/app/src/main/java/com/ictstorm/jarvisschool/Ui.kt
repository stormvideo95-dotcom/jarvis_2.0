package com.ictstorm.jarvisschool

import android.content.Context
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/** Tiny helpers so the screens stay code-only (dark + amber, like the Jarvis page). */
object Ui {
    const val BG = 0xFF0B0D12.toInt()
    const val CARD = 0xFF151924.toInt()
    const val LINE = 0xFF262C3B.toInt()
    const val TEXT = 0xFFE8EBF2.toInt()
    const val MUTED = 0xFF8B93A7.toInt()
    const val ACCENT = 0xFFFFB020.toInt()
    const val ON_ACCENT = 0xFF1B1200.toInt()

    fun dp(ctx: Context, v: Int) = (v * ctx.resources.displayMetrics.density).toInt()

    fun bg(ctx: Context, color: Int, radius: Int, stroke: Int = 0) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(ctx, radius).toFloat()
        if (stroke != 0) setStroke(dp(ctx, 1), stroke)
    }

    fun column(ctx: Context, padH: Int = 20, padTop: Int = 16) = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(ctx, padH), dp(ctx, padTop), dp(ctx, padH), dp(ctx, 24))
    }

    fun row(ctx: Context) = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }

    fun text(ctx: Context, s: String, size: Float = 16f, color: Int = TEXT, bold: Boolean = false) = TextView(ctx).apply {
        text = s; textSize = size; setTextColor(color)
        if (bold) typeface = Typeface.DEFAULT_BOLD
        setPadding(0, dp(ctx, 4), 0, dp(ctx, 4))
    }

    fun field(ctx: Context, hint: String, value: String, single: Boolean = true) = EditText(ctx).apply {
        setText(value); this.hint = hint; setTextColor(TEXT); setHintTextColor(MUTED); textSize = 16f
        background = bg(ctx, CARD, 14, LINE)
        setPadding(dp(ctx, 14), dp(ctx, 12), dp(ctx, 14), dp(ctx, 12))
        isSingleLine = single
        if (!single) maxLines = 5
    }

    fun button(ctx: Context, s: String, primary: Boolean = true, onClick: () -> Unit) = Button(ctx).apply {
        text = s; isAllCaps = false; textSize = 16f
        setTextColor(if (primary) ON_ACCENT else TEXT)
        background = bg(ctx, if (primary) ACCENT else LINE, 14)
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            .apply { topMargin = dp(ctx, 12) }
    }

    /** Outlined link button under a Jarvis message. */
    fun link(ctx: Context, s: String, onClick: () -> Unit) = TextView(ctx).apply {
        text = "↗  $s"; textSize = 14f; setTextColor(ACCENT)
        background = bg(ctx, 0, 10, ACCENT)
        setPadding(dp(ctx, 12), dp(ctx, 8), dp(ctx, 12), dp(ctx, 8))
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            .apply { topMargin = dp(ctx, 6) }
    }

    fun card(ctx: Context) = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        background = bg(ctx, CARD, 16, LINE)
        setPadding(dp(ctx, 16), dp(ctx, 12), dp(ctx, 16), dp(ctx, 12))
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            .apply { topMargin = dp(ctx, 12) }
    }

    fun wrap(v: View, ctx: Context, weight: Float = 0f) = v.apply {
        layoutParams = if (weight > 0) LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, weight)
        else LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    }
}
