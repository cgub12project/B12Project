package com.frauddetector.network

import com.google.gson.annotations.SerializedName

data class PhoneReportRequest(
    @SerializedName("fraud_type") val fraudType: String,
    val content: String,
    val description: String? = null
)

data class MessageReportBody(
    @SerializedName("fraud_type") val fraudType: String,
    val content: String,
    val platform: String,
    @SerializedName("account_name") val accountName: String,
    @SerializedName("account_id") val accountId: String? = null,
    val description: String? = null
)
