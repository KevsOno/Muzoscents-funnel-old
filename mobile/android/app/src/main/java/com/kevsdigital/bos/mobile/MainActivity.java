package com.kevsdigital.bos.mobile;

import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.BridgeWebViewClient;

public class MainActivity extends BridgeActivity {

    private boolean isPosPath(String url) {
        if (url == null) return false;
        try {
            String path = Uri.parse(url).getPath();
            if (path == null) return false;
            String lower = path.toLowerCase();
            return lower.startsWith("/kdpos") || lower.startsWith("/pos");
        } catch (Exception ignored) {
            return false;
        }
    }

    private void showOfflineFallback(WebView webView, String failedUrl) {
        String safeUrl = failedUrl == null ? "" : failedUrl.replace("'", "\\'");
        String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width,initial-scale=1.0'/>"
            + "<style>*{box-sizing:border-box;margin:0;padding:0}body{min-height:100vh;display:flex;align-items:center;"
            + "justify-content:center;padding:24px;background:#0F172A;color:#F8FAFC;font-family:system-ui,-apple-system,sans-serif}"
            + ".card{width:100%;max-width:380px;background:#1E293B;border:1px solid rgba(255,255,255,.1);"
            + "border-radius:16px;padding:28px 24px;text-align:center}"
            + "h1{font-size:20px;font-weight:700;margin-bottom:8px}"
            + "p{font-size:14px;line-height:1.5;color:#CBD5E1;margin-bottom:18px}"
            + ".pill{font-size:12px;color:#94A3B8;background:rgba(15,23,42,.65);border-radius:10px;padding:10px 12px;margin-bottom:18px}"
            + "button{width:100%;border:0;border-radius:10px;padding:13px 16px;font-size:15px;font-weight:600;"
            + "color:#fff;background:#2563EB;cursor:pointer}</style></head><body><div class='card'>"
            + "<h1>Kevs Digital bOS</h1>"
            + "<p>No active internet connection right now. Connect to Wi-Fi or mobile data to load this workspace.</p>"
            + "<div class='pill'>Offline mode active</div>"
            + "<button type='button' onclick=\"window.location.replace('" + safeUrl + "')\">Retry Connection</button>"
            + "</div></body></html>";
        webView.loadDataWithBaseURL("https://kevsbos.netlify.app/", html, "text/html", "UTF-8", null);
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (this.bridge != null && this.bridge.getWebView() != null) {
            WebView wv = this.bridge.getWebView();
            wv.setWebViewClient(new BridgeWebViewClient(this.bridge) {
                @Override
                public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                    super.onReceivedError(view, request, error);
                    if (request != null && request.isForMainFrame()) {
                        String url = request.getUrl() != null ? request.getUrl().toString() : view.getUrl();
                        if (!isPosPath(url)) {
                            showOfflineFallback(view, url);
                        }
                    }
                }
            });
        }
    }
}
