package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path

interface ReportApi {

    @POST("api/v1/reports/phone/{phone_number}")
    fun reportPhone(
        @Header("Authorization") token: String,
        @Path("phone_number") phoneNumber: String,
        @Body body: PhoneReportRequest
    ): Call<Void>

    @POST("api/v1/reports/account")
    fun reportAccount(
        @Header("Authorization") token: String,
        @Body body: MessageReportBody
    ): Call<Void>
}
