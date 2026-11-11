package com.iritech.irissample.sync.model;

/**
 * Trạng thái đồng bộ phục vụ hiển thị trên giao diện (UI)
 */
public enum SyncStatus {
    IDLE,       // Đang nghỉ, không có tác vụ đồng bộ nào
    SYNCING,    // Đang trong tiến trình Push/Pull dữ liệu
    SUCCESS,    // Lần đồng bộ gần nhất thành công
    ERROR,      // Đồng bộ thất bại (lỗi mạng hoặc lỗi server)
    SKIPPED     // Bỏ qua lượt gọi (do đang có tác vụ đồng bộ khác đang chạy)
}
