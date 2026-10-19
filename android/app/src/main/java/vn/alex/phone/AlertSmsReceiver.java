package vn.alex.phone;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public final class AlertSmsReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        String run = intent.getStringExtra("run"), op = intent.getStringExtra("op");
        int part = intent.getIntExtra("part", -1), total = intent.getIntExtra("total", 0);
        if (run == null || op == null || part < 0 || total < 1 || part >= total || total > 20) return;
        new AlertStore(context).smsPart(run, op, part, total, getResultCode() == Activity.RESULT_OK);
    }
}
