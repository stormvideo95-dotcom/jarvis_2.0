package com.ictstorm.jarvisschool

import android.content.Context
import android.graphics.PorterDuff
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

/** Light, soft-blue design: big rounded cards, black pill buttons, round white icon buttons. */
object Ui {
    const val BG = 0xFFF6F7FA.toInt()
    const val WHITE = 0xFFFFFFFF.toInt()
    const val SOFT = 0xFFEFF1F5.toInt()      // light grey chips / Jarvis bubbles
    const val LINE = 0xFFE4E7EE.toInt()
    const val BLUE = 0xFFA3B8FF.toInt()      // main soft blue
    const val BLUE_DARK = 0xFF7F96F0.toInt()
    const val BLUE_TINT = 0xFFE5EBFF.toInt()
    const val PINK = 0xFFE7A6F5.toInt()
    const val ORANGE = 0xFFF39A35.toInt()
    const val BLACK = 0xFF0F0F12.toInt()
    const val TEXT = 0xFF0F0F12.toInt()
    const val MUTED = 0xFF8A8F9C.toInt()

    // Outfit: rounded geometric font like the design
    var REG: Typeface = Typeface.DEFAULT
    var MEDIUM: Typeface = Typeface.DEFAULT_BOLD
    var SEMI: Typeface = Typeface.DEFAULT_BOLD

    fun init(ctx: Context) {
        runCatching {
            REG = ctx.resources.getFont(R.font.outfit_regular)
            MEDIUM = ctx.resources.getFont(R.font.outfit_medium)
            SEMI = ctx.resources.getFont(R.font.outfit_semibold)
        }
    }

    fun dp(ctx: Context, v: Int) = (v * ctx.resources.displayMetrics.density).toInt()

    fun shape(ctx: Context, color: Int, radius: Int, stroke: Int = 0) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(ctx, radius).toFloat()
        if (stroke != 0) setStroke(dp(ctx, 1), stroke)
    }

    fun circle(color: Int, ctx: Context, stroke: Int = 0) = GradientDrawable().apply {
        shape = GradientDrawable.OVAL; setColor(color)
        if (stroke != 0) setStroke(dp(ctx, 1), stroke)
    }

    fun lp(w: Int = ViewGroup.LayoutParams.MATCH_PARENT, h: Int = ViewGroup.LayoutParams.WRAP_CONTENT,
           top: Int = 0, right: Int = 0, weight: Float = 0f) =
        LinearLayout.LayoutParams(w, h, weight).apply { topMargin = top; rightMargin = right }

    fun column(ctx: Context, padH: Int = 20, padTop: Int = 12) = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(ctx, padH), dp(ctx, padTop), dp(ctx, padH), dp(ctx, 24))
    }

    fun row(ctx: Context) = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }

    fun text(ctx: Context, s: String, size: Float = 16f, color: Int = TEXT, bold: Boolean = false) = TextView(ctx).apply {
        text = s; textSize = size; setTextColor(color)
        typeface = if (bold) SEMI else REG
        setLineSpacing(0f, 1.12f)
    }

    fun icon(ctx: Context, res: Int, color: Int, size: Int = 22) = ImageView(ctx).apply {
        setImageResource(res)
        setColorFilter(color, PorterDuff.Mode.SRC_IN)
        layoutParams = LinearLayout.LayoutParams(dp(ctx, size), dp(ctx, size))
    }

    /** Round button with an icon in the middle (white with border, or black). */
    fun roundButton(ctx: Context, res: Int, dark: Boolean = false, size: Int = 48, onClick: () -> Unit) = FrameLayout(ctx).apply {
        background = if (dark) circle(BLACK, ctx) else circle(WHITE, ctx, LINE)
        addView(icon(ctx, res, if (dark) WHITE else BLACK, size * 9 / 20).apply {
            layoutParams = FrameLayout.LayoutParams(dp(ctx, size * 9 / 20), dp(ctx, size * 9 / 20), Gravity.CENTER)
        })
        layoutParams = LinearLayout.LayoutParams(dp(ctx, size), dp(ctx, size))
        isClickable = true
        setOnClickListener { onClick() }
    }

    /** Black (or white) pill button. */
    fun pill(ctx: Context, s: String, dark: Boolean = true, full: Boolean = false, onClick: () -> Unit) = TextView(ctx).apply {
        text = s; textSize = 13f; typeface = SEMI; gravity = Gravity.CENTER; letterSpacing = 0.04f
        setTextColor(if (dark) WHITE else BLACK)
        background = shape(ctx, if (dark) BLACK else WHITE, 28, if (dark) 0 else LINE)
        setPadding(dp(ctx, 22), dp(ctx, 13), dp(ctx, 22), dp(ctx, 13))
        setOnClickListener { onClick() }
        layoutParams = lp(if (full) ViewGroup.LayoutParams.MATCH_PARENT else ViewGroup.LayoutParams.WRAP_CONTENT,
            top = dp(ctx, 14))
    }

    /** Small chip (black when selected, light grey otherwise). */
    fun chip(ctx: Context, s: String, on: Boolean, onClick: () -> Unit) = TextView(ctx).apply {
        text = s; textSize = 13f; typeface = MEDIUM; gravity = Gravity.CENTER
        includeFontPadding = false
        setTextColor(if (on) WHITE else BLACK)
        background = shape(ctx, if (on) BLACK else SOFT, 20)
        setPadding(dp(ctx, 14), dp(ctx, 9), dp(ctx, 14), dp(ctx, 9))
        setOnClickListener { onClick() }
        layoutParams = lp(ViewGroup.LayoutParams.WRAP_CONTENT, right = dp(ctx, 8), top = dp(ctx, 8))
    }

    /** Link button under a Jarvis message / in a week card. */
    fun link(ctx: Context, s: String, onWhite: Boolean = true, onClick: () -> Unit) = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        background = shape(ctx, if (onWhite) BLUE_TINT else WHITE, 22)
        setPadding(dp(ctx, 8), dp(ctx, 7), dp(ctx, 16), dp(ctx, 7))
        val dot = FrameLayout(ctx).apply {
            background = circle(BLACK, ctx)
            addView(icon(ctx, R.drawable.ic_arrow, WHITE, 14).apply {
                layoutParams = FrameLayout.LayoutParams(dp(ctx, 14), dp(ctx, 14), Gravity.CENTER)
            })
        }
        addView(dot, LinearLayout.LayoutParams(dp(ctx, 28), dp(ctx, 28)).apply { rightMargin = dp(ctx, 10) })
        addView(text(ctx, s, 13f, BLACK, bold = true))
        isClickable = true
        setOnClickListener { onClick() }
        layoutParams = lp(ViewGroup.LayoutParams.WRAP_CONTENT, top = dp(ctx, 8))
    }

    fun card(ctx: Context, color: Int = WHITE, radius: Int = 28, stroke: Int = 0) = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        background = shape(ctx, color, radius, stroke)
        setPadding(dp(ctx, 20), dp(ctx, 18), dp(ctx, 20), dp(ctx, 18))
        layoutParams = lp(top = dp(ctx, 14))
    }

    fun field(ctx: Context, hint: String, value: String, single: Boolean = true) = EditText(ctx).apply {
        setText(value); this.hint = hint; setTextColor(TEXT); setHintTextColor(MUTED); textSize = 15f; typeface = REG
        background = shape(ctx, WHITE, 18, LINE)
        setPadding(dp(ctx, 16), dp(ctx, 14), dp(ctx, 16), dp(ctx, 14))
        isSingleLine = single
        if (!single) maxLines = 5
    }

    fun spacer(ctx: Context) = View(ctx).apply { layoutParams = LinearLayout.LayoutParams(0, 1, 1f) }
}
