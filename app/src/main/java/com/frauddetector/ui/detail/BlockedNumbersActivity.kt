/**
 * BlockedNumbersActivity.kt — 封鎖名單頁面
 *
 * 所屬模組：ui/detail（詳情模組）
 *
 * 顯示目前所有本機封鎖的電話號碼（[BlockedNumbersManager]），並可個別解封。
 * 封鎖名單為純本地功能，僅影響「電話」分頁列表是否顯示該號碼，不涉及後端資料。
 */
package com.frauddetector.ui.detail

import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import com.frauddetector.ui.BaseActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.service.BlockedNumbersManager

class BlockedNumbersActivity : BaseActivity() {

    private lateinit var adapter: BlockedNumberAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_blocked_numbers)

        findViewById<View>(R.id.btnBack).setOnClickListener { finish() }

        adapter = BlockedNumberAdapter { number ->
            BlockedNumbersManager.toggle(this, number)
            refresh()
        }
        findViewById<RecyclerView>(R.id.rvBlockedNumbers).apply {
            layoutManager = LinearLayoutManager(this@BlockedNumbersActivity)
            adapter = this@BlockedNumbersActivity.adapter
        }

        refresh()
    }

    private fun refresh() {
        val numbers = BlockedNumbersManager.getAll(this).sorted()
        adapter.updateItems(numbers)
        findViewById<TextView>(R.id.tvEmpty).visibility = if (numbers.isEmpty()) View.VISIBLE else View.GONE
    }
}

private class BlockedNumberAdapter(
    private val onUnblock: (String) -> Unit
) : RecyclerView.Adapter<BlockedNumberAdapter.VH>() {

    private var items: List<String> = emptyList()

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val tvNumber: TextView = view.findViewById(R.id.tvBlockedNumber)
        val tvUnblock: TextView = view.findViewById(R.id.tvUnblock)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_blocked_number, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val number = items[position]
        val dp = holder.itemView.resources.displayMetrics.density

        holder.tvNumber.text = number
        holder.itemView.background = GradientDrawable().apply {
            setColor(Color.parseColor("#FDFAF4"))
            cornerRadius = 14f * dp
            setStroke((1 * dp).toInt(), Color.parseColor("#1AC8C4C0"))
        }
        holder.tvUnblock.setOnClickListener { onUnblock(number) }
    }

    override fun getItemCount() = items.size

    fun updateItems(newItems: List<String>) {
        items = newItems
        notifyDataSetChanged()
    }
}
