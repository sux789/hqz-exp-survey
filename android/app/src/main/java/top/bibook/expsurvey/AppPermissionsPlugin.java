package top.bibook.expsurvey;

import android.Manifest;
import android.app.Activity;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.provider.Settings;
import android.util.Base64;

import androidx.activity.result.ActivityResult;
import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * 原生相机 + 相册写入插件（v1.5，doc/010）。
 *
 * 页面调用：
 *   - takePhoto()                   打开系统相机（ACTION_IMAGE_CAPTURE，只给相机，不弹相册选择），
 *                                   成功返回 {path}（本 App 缓存目录里的原片）
 *   - readPhoto({path})             读缓存原片为 base64（页面 fetch(convertFileSrc) 失败时兜底）
 *   - savePhoto({base64,name,subdir})  压缩+水印后的成品写入系统相册 Pictures/{subdir}/，
 *                                   返回真实绝对路径；subdir 支持多级（如 2025年度/XP-01）
 *   - removeCacheFile({path})       删掉拍照缓存的原片（成品已落相册，原片没有保留价值）
 *   - getLastPhoto({consume})       取「拍完但没存进相册」的原片（页面被系统重载后补存，见 doc/011）
 *   - clearLastPhoto()              丢掉待补存标记（正常流程存相册成功后调用）
 *   - check({type}) / request({type}) / openSettings()   相机权限查询与申请
 *
 * 为什么自己做相机：WebView 的 <input capture> 在部分机型/系统上仍会弹出「相机还是相册」，
 * 而外业要求照片只能现拍、不能从相册挑旧图。
 *
 * 两处机型差异必须按「文件真的有内容」判断，不能只看 resultCode：
 *   · 华为/鸿蒙部分机型拍完写盘成功却回 RESULT_CANCELED；
 *   · 相机 Activity 常把 WebView 顶掉，页面回来是全新加载，回调里的 call 为 null。
 *
 * 写入相册走 MediaStore（Android 10+ 自有媒体免存储权限，相册立即可见，多级目录自动创建）；
 * 旧版本回退应用外部私有目录（不需要 WRITE_EXTERNAL_STORAGE）。
 */
@CapacitorPlugin(
    name = "AppPermissions",
    permissions = {
        @Permission(alias = "camera", strings = { Manifest.permission.CAMERA })
    }
)
public class AppPermissionsPlugin extends Plugin {

    /** 待补存原片：路径写 SharedPreferences，插件实例被系统回收后仍能捞回（鸿蒙实测会回收）。 */
    private static final String PREFS = "exp_photo_pending";
    private static final String KEY_PENDING_PATH = "path";
    private static final String KEY_PENDING_AT = "at";
    private static final long RECOVER_WINDOW_MS = 15 * 60 * 1000L;

    /** 相机 Activity 是异步返回的，路径先存字段；进程被回收时回调里 call 为 null。 */
    private String pendingPhotoPath;

    @PluginMethod
    public void check(PluginCall call) {
        PermissionState state = getPermissionState("camera");
        if (state == null) state = PermissionState.DENIED;
        JSObject ret = new JSObject();
        ret.put("type", "camera");
        ret.put("state", state.toString());
        ret.put("granted", state == PermissionState.GRANTED);
        call.resolve(ret);
    }

    @PluginMethod
    public void request(PluginCall call) {
        requestPermissionForAlias("camera", call, "permissionCallback");
    }

    @PermissionCallback
    private void permissionCallback(PluginCall call) {
        PermissionState state = getPermissionState("camera");
        JSObject ret = new JSObject();
        ret.put("type", "camera");
        ret.put("state", state == null ? "DENIED" : state.toString());
        ret.put("granted", state == PermissionState.GRANTED);
        call.resolve(ret);
    }

    @PluginMethod
    public void openSettings(PluginCall call) {
        try {
            Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
            intent.setData(Uri.parse("package:" + getContext().getPackageName()));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
            call.resolve();
        } catch (Exception e) {
            call.reject("无法打开系统设置", e);
        }
    }

    /* ── 相机 ───────────────────────────────────────────────────── */

    @PluginMethod
    public void takePhoto(PluginCall call) {
        if (getPermissionState("camera") != PermissionState.GRANTED) {
            requestPermissionForAlias("camera", call, "cameraPermissionCallback");
            return;
        }
        launchCamera(call);
    }

    @PermissionCallback
    private void cameraPermissionCallback(PluginCall call) {
        if (getPermissionState("camera") == PermissionState.GRANTED) {
            launchCamera(call);
        } else {
            call.reject("没有相机权限，请在系统设置里允许「抚育调查」使用相机");
        }
    }

    private void launchCamera(PluginCall call) {
        try {
            File dir = new File(getContext().getCacheDir(), "camera");
            if (!dir.exists() && !dir.mkdirs()) {
                call.reject("无法创建拍照缓存目录");
                return;
            }
            File target = new File(dir, "cap_" + System.currentTimeMillis() + ".jpg");
            pendingPhotoPath = target.getAbsolutePath();
            // 关键：**启动相机前**就把路径写进 SharedPreferences。
            // 鸿蒙/EMUI 上相机是独立 Activity，内存紧张时会把 WebView 连同本插件实例一起回收，
            // 页面回来是全新加载的 —— 那时 cameraResult 里的 call 为 null，原片路径只剩这份落盘记录。
            // 页面通过 getLastPhoto 把它捞回来继续压缩、加水印、存相册。
            getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                    .putString(KEY_PENDING_PATH, pendingPhotoPath)
                    .putLong(KEY_PENDING_AT, System.currentTimeMillis())
                    .apply();
            Uri uri = FileProvider.getUriForFile(
                    getContext(), getContext().getPackageName() + ".fileprovider", target);
            Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            intent.putExtra(MediaStore.EXTRA_OUTPUT, uri);
            intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivityForResult(call, intent, "cameraResult");
        } catch (Exception e) {
            pendingPhotoPath = null;
            clearPending();
            call.reject("无法启动相机: " + e.getMessage(), e);
        }
    }

    @ActivityCallback
    private void cameraResult(PluginCall call, ActivityResult result) {
        String path = pendingPhotoPath;
        if (path == null) {
            path = pendingPathFromPrefs();          // 插件实例被重建时只能靠落盘记录
        }
        pendingPhotoPath = null;
        File file = path == null ? null : new File(path);
        boolean hasPhoto = file != null && file.exists() && file.length() > 0;
        boolean okResult = result != null && result.getResultCode() == Activity.RESULT_OK;

        if (call == null) {
            // WebView 已重建：页面会在恢复时用 getLastPhoto 接管，这里只保留已经落盘的原片
            if (!hasPhoto) clearPending();
            return;
        }
        // 华为/鸿蒙实测：部分机型明明已写盘却回 RESULT_CANCELED。
        // 判据以「文件真的有内容」为准，resultCode 只作参考，否则会把拍好的照片误删。
        if (!hasPhoto) {
            clearPending();
            if (okResult) {
                call.reject("相机没有生成照片");
            } else {
                call.reject("已取消拍照");
            }
            return;
        }
        call.resolve(resultOf(path));
    }

    /**
     * 取「上一次拍照留下但还没存进相册」的原片（页面被系统重载后补存用）。
     * consume=true 时读完即清标记，避免重复入库；文件不存在/为空/超过 15 分钟视为没有。
     */
    @PluginMethod
    public void getLastPhoto(PluginCall call) {
        boolean consume = call.getBoolean("consume", Boolean.TRUE);
        String path = pendingPathFromPrefs();
        long at = getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getLong(KEY_PENDING_AT, 0L);
        JSObject ret = new JSObject();
        if (path != null) {
            File file = new File(path);
            long age = System.currentTimeMillis() - at;
            if (file.exists() && file.length() > 0 && age <= RECOVER_WINDOW_MS) {
                ret.put("path", path);
                ret.put("takenAt", at);
            }
        }
        if (consume) clearPending();
        call.resolve(ret);
    }

    /** 明确丢掉待补存标记（正常流程存相册成功后调用）。 */
    @PluginMethod
    public void clearLastPhoto(PluginCall call) {
        clearPending();
        call.resolve();
    }

    private String pendingPathFromPrefs() {
        return getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(KEY_PENDING_PATH, null);
    }

    private void clearPending() {
        getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .remove(KEY_PENDING_PATH).remove(KEY_PENDING_AT).apply();
    }

    private JSObject resultOf(String path) {
        JSObject ret = new JSObject();
        ret.put("path", path);
        return ret;
    }

    /* ── 相册写入 ────────────────────────────────────────────────── */

    /**
     * 成品照片写入系统相册 Pictures/{subdir}/。
     * subdir 为多级子目录（如 "2025年度中幼林抚育/XP-01"），缺省 "抚育调查"；
     * 每段自动清理非法字符并挡掉路径穿越（. / ..）。
     */
    @PluginMethod
    public void savePhoto(PluginCall call) {
        String base64 = call.getString("base64");
        String name = call.getString("name", "photo.jpg");
        if (base64 == null || base64.isEmpty()) {
            call.reject("缺少照片数据");
            return;
        }
        String subdir = sanitizeSubdir(call.getString("subdir", "抚育调查"));
        String mime = name.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg";
        try {
            byte[] bytes = Base64.decode(base64, Base64.DEFAULT);
            ContentValues values = new ContentValues();
            values.put(MediaStore.Images.Media.DISPLAY_NAME, name);
            values.put(MediaStore.Images.Media.MIME_TYPE, mime);
            String realPath;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                values.put(MediaStore.Images.Media.RELATIVE_PATH,
                        Environment.DIRECTORY_PICTURES + "/" + subdir);
                Uri uri = getContext().getContentResolver().insert(
                        MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values);
                if (uri == null) {
                    call.reject("创建相册记录失败");
                    return;
                }
                try (OutputStream os = getContext().getContentResolver().openOutputStream(uri)) {
                    os.write(bytes);
                    os.flush();
                }
                File fallback = new File(new File(
                        Environment.getExternalStorageDirectory(), Environment.DIRECTORY_PICTURES), subdir);
                realPath = queryRealPath(uri, new File(fallback, name));
            } else {
                File dir = new File(getContext().getExternalFilesDir(Environment.DIRECTORY_PICTURES), subdir);
                if (!dir.exists() && !dir.mkdirs()) {
                    call.reject("创建照片目录失败");
                    return;
                }
                File target = new File(dir, name);
                try (FileOutputStream fos = new FileOutputStream(target)) {
                    fos.write(bytes);
                    fos.flush();
                }
                realPath = target.getAbsolutePath();
            }
            JSObject ret = new JSObject();
            ret.put("path", realPath);
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("保存照片失败: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void readPhoto(PluginCall call) {
        String path = call.getString("path");
        if (path == null || path.isEmpty()) {
            call.reject("缺少文件路径");
            return;
        }
        File file = new File(path);
        if (!insideCache(file)) {
            call.reject("只允许读取本 App 缓存目录里的拍照文件");
            return;
        }
        try {
            long size = file.length();
            if (size <= 0) {
                call.reject("照片文件不存在或为空");
                return;
            }
            ByteArrayOutputStream buffer = new ByteArrayOutputStream((int) size);
            try (InputStream in = new FileInputStream(file)) {
                byte[] chunk = new byte[8192];
                int read;
                while ((read = in.read(chunk)) != -1) buffer.write(chunk, 0, read);
            }
            JSObject ret = new JSObject();
            ret.put("base64", Base64.encodeToString(buffer.toByteArray(), Base64.NO_WRAP));
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("读取照片失败: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void removeCacheFile(PluginCall call) {
        String path = call.getString("path");
        if (path == null || path.isEmpty()) {
            call.resolve();
            return;
        }
        File file = new File(path);
        if (insideCache(file)) deleteQuietly(path);
        call.resolve();
    }

    /* ── 内部工具 ───────────────────────────────────────────────── */

    private boolean insideCache(File file) {
        try {
            String cache = getContext().getCacheDir().getCanonicalPath();
            return file.getCanonicalPath().startsWith(cache + File.separator);
        } catch (Exception e) {
            return false;
        }
    }

    private void deleteQuietly(String path) {
        if (path == null) return;
        try {
            File file = new File(path);
            if (file.exists()) file.delete();
        } catch (Exception ignored) {
            // 缓存清理失败不影响成品照片
        }
    }

    /** MediaStore 记录的真实路径；查不到时返回"相册标准目录/文件名"这个可读路径。 */
    private String queryRealPath(Uri uri, File fallback) {
        try (android.database.Cursor cursor = getContext().getContentResolver().query(
                uri, new String[] { MediaStore.MediaColumns.DATA }, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int index = cursor.getColumnIndex(MediaStore.MediaColumns.DATA);
                if (index >= 0) {
                    String value = cursor.getString(index);
                    if (value != null && !value.isEmpty()) return value;
                }
            }
        } catch (Exception ignored) {
            // Android 10+ 部分机型对 DATA 列返回空，用可读路径兜底
        }
        return fallback.getAbsolutePath();
    }

    /** 清理子目录串：去每段非法字符、空段与路径穿越（. / ..），全空时回退「抚育调查」。 */
    private String sanitizeSubdir(String raw) {
        if (raw == null || raw.trim().isEmpty()) return "抚育调查";
        StringBuilder builder = new StringBuilder();
        for (String segment : raw.split("/")) {
            String cleaned = segment.trim().replaceAll("[\\\\/:*?\"<>|\\s]+", "_");
            if (cleaned.isEmpty() || cleaned.equals(".") || cleaned.equals("..")) continue;
            if (cleaned.startsWith("_") && cleaned.length() > 1) cleaned = cleaned.substring(1);
            if (builder.length() > 0) builder.append('/');
            builder.append(cleaned);
        }
        return builder.length() > 0 ? builder.toString() : "抚育调查";
    }
}
