package top.bibook.expsurvey;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // 原生能力必须在 super.onCreate 之前登记，否则 WebView 里的 Capacitor.Plugins 拿不到
        registerPlugin(AppPermissionsPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
