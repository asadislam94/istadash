package io.github.asadislam94.istadash

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.LinearLayout
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.Kwarg
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

class MainActivity : AppCompatActivity() {
    companion object {
        @Volatile var flaskStarted = false
    }

    private lateinit var webView: WebView
    private lateinit var loadingView: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        loadingView = findViewById(R.id.loadingView)

        // Show splash, hide WebView
        loadingView.visibility = View.VISIBLE
        webView.visibility = View.GONE

        // Initialize Chaquopy
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        // Start Flask once (survives Activity recreation)
        if (!flaskStarted) {
            flaskStarted = true
            Thread {
                try {
                    val py = Python.getInstance()
                    val main = py.getModule("istadash.main")
                    val app = main.callAttr("create_app")
                    app.callAttr("run",
                        Kwarg("host", "127.0.0.1"),
                        Kwarg("port", 8000),
                        Kwarg("debug", false),
                        Kwarg("use_reloader", false))
                } catch (e: Exception) {
                    runOnUiThread { showError("Flask failed to start: ${e.message}") }
                }
            }.start()
        }

        // Configure WebView
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?, request: WebResourceRequest?
            ): Boolean {
                val url = request?.url?.toString() ?: return false
                if (url.startsWith("http://127.0.0.1")) return false
                // External URL -> system browser
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                return true
            }
        }

        // Poll Flask, then show WebView
        pollFlaskAndLoad()
    }

    private fun pollFlaskAndLoad() {
        Thread {
            var ready = false
            for (i in 1..30) {  // 30 x 500ms = 15s max
                try {
                    val conn = java.net.URL("http://127.0.0.1:8000")
                        .openConnection() as java.net.HttpURLConnection
                    conn.connectTimeout = 1000
                    conn.connect()
                    conn.disconnect()
                    ready = true
                    break
                } catch (_: Exception) {
                    Thread.sleep(500)
                }
            }
            runOnUiThread {
                if (ready) {
                    loadingView.visibility = View.GONE
                    webView.visibility = View.VISIBLE
                    webView.loadUrl("http://127.0.0.1:8000")
                } else {
                    showError("Server didn't respond after 15 seconds.")
                }
            }
        }.start()
    }

    private fun showError(message: String) {
        loadingView.visibility = View.GONE
        webView.visibility = View.VISIBLE
        webView.loadDataWithBaseURL(null,
            """<html><body style="background:#1a1a2e;color:#e2e8f0;font-family:sans-serif;
               display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
               <div style="text-align:center"><h2>⚠️ IstaDash</h2>
               <p>$message</p></div></body></html>""",
            "text/html", "utf-8", null)
    }

    @Deprecated("Deprecated in API 33+")
    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) {
            webView.goBack()
        } else {
            @Suppress("DEPRECATION")
            super.onBackPressed()
        }
    }
}
