package com.iritech.irissample.sync.api;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotSame;
import static org.junit.Assert.assertSame;

import com.iritech.irissample.sync.data.InMemorySyncPrefs;
import org.junit.Before;
import org.junit.Test;

/**
 * Unit Test kiểm chứng cơ chế caching và thread-safe của SyncApiFactory
 */
public class SyncApiFactoryTest {

    private InMemorySyncPrefs prefs;

    @Before
    public void setUp() {
        SyncApiFactory.clearCache();
        prefs = new InMemorySyncPrefs();
        prefs.setServerUrl("http://192.168.1.50:5000");
        prefs.setAuthToken("sample_token_abc");
    }

    @Test
    public void test_CreateService_SameUrlAndToken_ShouldReturnCachedInstance() {
        SyncApiService service1 = SyncApiFactory.createService(prefs);
        SyncApiService service2 = SyncApiFactory.createService(prefs);

        // Cùng cấu hình -> Phải tái sử dụng đúng instance cũ, không tạo mới
        assertSame("Service instance phải được cache và tái sử dụng", service1, service2);
    }

    @Test
    public void test_CreateService_WhenBaseUrlChanges_ShouldCreateNewService() {
        SyncApiService service1 = SyncApiFactory.createService(prefs);

        // Đổi IP/Domain máy chủ trong Cài đặt
        prefs.setServerUrl("http://192.168.1.99:5000");
        SyncApiService service2 = SyncApiFactory.createService(prefs);

        assertNotSame("Khi đổi URL máy chủ, factory bắt buộc phải tạo Retrofit service mới", service1, service2);
    }

    @Test
    public void test_NormalizeAndValidateBaseUrl_FormattingRules() {
        assertEquals("http://127.0.0.1:5000/", SyncApiFactory.normalizeAndValidateBaseUrl(null));
        assertEquals("http://127.0.0.1:5000/", SyncApiFactory.normalizeAndValidateBaseUrl("   "));
        assertEquals("http://192.168.1.100:5000/", SyncApiFactory.normalizeAndValidateBaseUrl("192.168.1.100:5000"));
        assertEquals("https://api.hkdn.edu.vn/", SyncApiFactory.normalizeAndValidateBaseUrl("https://api.hkdn.edu.vn"));
    }
}
