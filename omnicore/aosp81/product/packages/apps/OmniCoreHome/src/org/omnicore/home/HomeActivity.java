package org.omnicore.home;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Offline-first HOME for Android API 27. No remote services or permissions. */
public final class HomeActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(16, 16, 16, 16);
        root.setBackgroundColor(Color.rgb(14, 18, 25));

        View emblem = new View(this) {
            private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            @Override
            protected void onDraw(Canvas canvas) {
                super.onDraw(canvas);
                float cx = getWidth() / 2.0f;
                float cy = getHeight() / 2.0f;
                paint.setColor(Color.rgb(58, 145, 232));
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(5.0f);
                canvas.drawCircle(cx, cy, Math.min(getWidth(), getHeight()) * 0.3f, paint);
                paint.setStyle(Paint.Style.FILL);
                paint.setColor(Color.WHITE);
                paint.setTextSize(24.0f);
                paint.setTextAlign(Paint.Align.CENTER);
                canvas.drawText("OMNICORE Ω", cx, cy + 10.0f, paint);
            }
        };
        emblem.setContentDescription("OmniCore Omega");
        root.addView(emblem, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 250));

        TextView status = new TextView(this);
        status.setText(R.string.status);
        status.setTextColor(Color.WHITE);
        status.setGravity(Gravity.CENTER);
        root.addView(status, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        addButton(root, R.string.phone, new Intent(Intent.ACTION_DIAL));
        Intent files = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        files.addCategory(Intent.CATEGORY_OPENABLE);
        files.setType("*/*");
        addButton(root, R.string.files, files);
        addButton(root, R.string.settings, new Intent(Settings.ACTION_SETTINGS));
        setContentView(root);
    }

    private void addButton(LinearLayout parent, int titleId, final Intent intent) {
        Button b = new Button(this);
        b.setText(titleId);
        b.setOnClickListener(v -> {
            if (intent.resolveActivity(getPackageManager()) != null) {
                startActivity(intent);
            }
        });
        parent.addView(b, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
    }
}