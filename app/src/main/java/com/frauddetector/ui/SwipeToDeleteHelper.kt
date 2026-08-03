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
        val deleteColor = Color.parseColor("#A63D2F")

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
                val paint = Paint().apply { color = deleteColor }
                val rect = RectF(
                    itemView.right + dX,
                    itemView.top.toFloat(),
                    itemView.right.toFloat(),
                    itemView.bottom.toFloat()
                )
                c.drawRoundRect(rect, 14f * dp, 14f * dp, paint)

                val icon = context.getDrawable(android.R.drawable.ic_menu_delete)
                icon?.setTint(Color.WHITE)
                if (icon != null) {
                    val iconSize = (22 * dp).toInt()
                    val margin = (16 * dp).toInt()
                    val iconTop = itemView.top + (itemView.height - iconSize) / 2
                    val iconRight = itemView.right - margin
                    icon.setBounds(iconRight - iconSize, iconTop, iconRight, iconTop + iconSize)
                    icon.draw(c)
                }
            }
        }

        ItemTouchHelper(callback).attachToRecyclerView(recyclerView)
    }
}
