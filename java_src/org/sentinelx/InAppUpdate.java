package org.sentinelx;

import android.app.Activity;

import com.google.android.gms.tasks.OnSuccessListener;
import com.google.android.play.core.appupdate.AppUpdateInfo;
import com.google.android.play.core.appupdate.AppUpdateManager;
import com.google.android.play.core.appupdate.AppUpdateManagerFactory;
import com.google.android.play.core.appupdate.AppUpdateOptions;
import com.google.android.play.core.install.InstallState;
import com.google.android.play.core.install.InstallStateUpdatedListener;
import com.google.android.play.core.install.model.AppUpdateType;
import com.google.android.play.core.install.model.InstallStatus;
import com.google.android.play.core.install.model.UpdateAvailability;

/**
 * Thin wrapper around the Play In-App Updates API.
 *
 * The Task/listener/activity-result flow is awkward to drive from pyjnius, so the
 * Python layer simply calls InAppUpdate.start(activity). On a Play Store install
 * this triggers a FLEXIBLE update (downloads in the background, then auto-installs
 * once ready). On a sideloaded build Play Core reports no update / errors, and this
 * no-ops — the app's GitHub OTA path handles those installs instead.
 */
public class InAppUpdate {

    private static final int REQUEST_CODE = 14010;
    private static AppUpdateManager manager;
    private static InstallStateUpdatedListener listener;

    public static void start(final Activity activity) {
        if (activity == null) {
            return;
        }
        try {
            manager = AppUpdateManagerFactory.create(activity.getApplicationContext());

            // Auto-complete a flexible update as soon as it finishes downloading.
            listener = new InstallStateUpdatedListener() {
                @Override
                public void onStateUpdate(InstallState state) {
                    try {
                        if (state.installStatus() == InstallStatus.DOWNLOADED && manager != null) {
                            manager.completeUpdate();
                        }
                    } catch (Throwable ignored) {
                    }
                }
            };
            manager.registerListener(listener);

            manager.getAppUpdateInfo().addOnSuccessListener(new OnSuccessListener<AppUpdateInfo>() {
                @Override
                public void onSuccess(final AppUpdateInfo info) {
                    try {
                        if (info.updateAvailability() == UpdateAvailability.UPDATE_AVAILABLE
                                && info.isUpdateTypeAllowed(AppUpdateType.FLEXIBLE)) {
                            activity.runOnUiThread(new Runnable() {
                                @Override
                                public void run() {
                                    try {
                                        manager.startUpdateFlowForResult(
                                                info,
                                                activity,
                                                AppUpdateOptions.newBuilder(AppUpdateType.FLEXIBLE).build(),
                                                REQUEST_CODE);
                                    } catch (Throwable ignored) {
                                    }
                                }
                            });
                        }
                    } catch (Throwable ignored) {
                    }
                }
            });
        } catch (Throwable ignored) {
            // Play Core unavailable (e.g. sideloaded) -> silently no-op.
        }
    }
}
