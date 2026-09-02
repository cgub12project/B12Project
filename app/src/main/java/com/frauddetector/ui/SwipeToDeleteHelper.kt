package com.frauddetector.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import androidx.appcompat.app.AlertDialog
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.RecyclerView

/**
 * 幫 RecyclerView 加上「左滑刪除」手勢，滑到底先跳確認對話框，
 * 確認才真的執行刪除，取消／關閉對話框則把項目滑回原位（不會誤刪）。
 *
 * 只負責手勢＋確認對話框＋滑動時的紅底垃圾桶背景這些 UI 邏輯，
 * 實際的「刪什麼、怎麼刪」交給呼叫端的 lambda 處理（各分頁的資料模型不同）。
 */
object SwipeToDeleteHelper {

    fun attach(
        context: Context,
        recyclerView: RecyclerView,
        getLabel: (Int) -> String,
        onConfirmedDelete: (Int) -> Unit,
        onCanceled: (Int) -> Unit
    ) {
        // 2026-08-18：卡片本身依風險上色後，滑動背景固定用銹紅在「高風險（同樣是銹紅）」的
        // 卡片上會完全融進去、看起來像沒反應。改成「銹紅底 + 米白邊框 + 米白圓底裝垃圾桶」，
        // 邊框在任何卡片顏色（含銹紅卡本身）都能切出一圈看得見的邊界；圖示改放進米白圓底
        // 裡、圖示本身用銹紅著色——這組「米白圓底＋卡片色字形」正是 RiskCardStyle 給彩色卡
        // 頭像用的同一套配色邏輯，滑動背景因此跟卡片本身的視覺語言一致，不是另外發明一套。
        val deleteColor = Color.parseColor("#A63D2F")
        val badgeColor = Color.parseColor("#FDFAF4")

        val callback = object : ItemTouchHelper.SimpleCallback(0, ItemTouchHelper.LEFT) {
            override fun onMove(
                rv: RecyclerView,
                viewHolder: RecyclerView.ViewHolder,
                target: RecyclerView.ViewHolder
            ) = false

            override fun onSwiped(viewHolder: RecyclerView.ViewHolder, direction: Int) {
                val position = viewHolder.bindingAdapterPosition
                if (position == RecyclerView.NO_POSITION) return

                AlertDialog.Builder(context)
                    .setTitle("刪除對話")
                    .setMessage("確定要刪除「${getLabel(position)}」的本機訊息紀錄嗎？此操作無法復原。")
                    .setPositiveButton("刪除") { _, _ -> onConfirmedDelete(position) }
                    .setNegativeButton("取消") { _, _ -> onCanceled(position) }
                    .setOnCancelListener { onCanceled(position) }
                    .show()
            }

            override fun onChildDraw(
                c: Canvas,
                rv: RecyclerView,
                viewHolder: RecyclerView.ViewHolder,
                dX: Float,
                dY: Float,
                actionState: Int,
                isCurrentlyActive: Boolean
            ) {
                super.onChildDraw(c, rv, viewHolder, dX, dY, actionState, isCurrentlyActive)
                if (actionState != ItemTouchHelper.ACTION_STATE_SWIPE || dX >= 0) return

                val itemView = viewHolder.itemView
                val dp = itemView.resources.displayMetrics.density
                val cornerRadius = 14f * dp
                val rect = RectF(
                    itemView.right + dX,
                    itemView.top.toFloat(),
                    itemView.right.toFloat(),
                    itemView.bottom.toFloat()
                )

                val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = deleteColor }
                c.drawRoundRect(rect, cornerRadius, cornerRadius, fillPaint)

                // 米白邊框：確保這塊滑動背景在任何卡片顏色（包含同色的高風險銹紅卡）上
                // 都切得出一圈清楚的邊界，不會被卡片本身的顏色吃掉
                val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                    color = badgeColor
                    style = Paint.Style.STROKE
                    strokeWidth = 1.5f * dp
                }
                val borderInset = borderPaint.strokeWidth / 2
                c.drawRoundRect(
                    RectF(
                        rect.left + borderInset,
                        rect.top + borderInset,
                        rect.right - borderInset,
                        rect.bottom - borderInset
                    ),
                    cornerRadius, cornerRadius, borderPaint
                )

                // 垃圾桶圖示放進米白圓底，圖示本身著色成銹紅——跟 RiskCardStyle 彩色卡
                // 頭像「米白圓底＋卡片色字形」同一套邏輯，視覺上跟卡片本身是同一家人
                val margin = 16f * dp
                val badgeRadius = 15f * dp
                val badgeCenterX = itemView.right - margin - badgeRadius
                val badgeCenterY = itemView.top + itemView.height / 2f
                if (badgeCenterX - badgeRadius > rect.left) {
                    val badgePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = badgeColor }
                    c.drawCircle(badgeCenterX, badgeCenterY, badgeRadius, badgePaint)

                    val icon = context.getDrawable(android.R.drawable.ic_menu_delete)
                    icon?.setTint(deleteColor)
                    if (icon != null) {
                        val iconSize = (18 * dp).toInt()
                        icon.setBounds(
                            (badgeCenterX - iconSize / 2).toInt(),
                            (badgeCenterY - iconSize / 2).toInt(),
                            (badgeCenterX + iconSize / 2).toInt(),
                            (badgeCenterY + iconSize / 2).toInt()
                        )
                        icon.draw(c)
                    }
                }
            }
        }

        ItemTouchHelper(callback).attachToRecyclerView(recyclerView)
    }
}
