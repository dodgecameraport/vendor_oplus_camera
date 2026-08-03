# Blob dependencies
PRODUCT_PACKAGES += \
    android.hardware.graphics.common-V3-ndk.vendor

# Framework
# PRODUCT_BOOT_JARS += \
#    oplus-framework

# Init
#PRODUCT_PACKAGES += \
#    init.oplus.camera.rc

# Permissions
PRODUCT_COPY_FILES += \
    $(LOCAL_PATH)/configs/permissions/oplus_google_lens_config.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/oplus_google_lens_config.xml \
    $(LOCAL_PATH)/configs/permissions/privapp-permissions-oplus.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/privapp-permissions-oplus.xml \
    $(LOCAL_PATH)/configs/sysconfig/hiddenapi-package-oplus-whitelist.xml:$(TARGET_COPY_OUT_SYSTEM)/etc/sysconfig/hiddenapi-package-oplus-whitelist.xml

# ColorOS version identity.
#
# oplus.api is load-bearing, not cosmetic: OplusBuild.getOplusOSVERSION() reads it
# and AIUnit's UnitConfig.isWhiteConditionsMatch() requires that value to be >=
# each unit's minColorApi. The Gallery AI units declare 30. Without this the
# legacy VERSIONS table walk caps out at 24, every unit reports support:false and
# Gallery fails with "unit config not found" the moment a tool is used.
#
# The oplusrom trio is what the Odin cloud endpoints read as device identity;
# empty values there make the AI inference API reject requests with 3000404
# (请求头缺失 / "request header missing"). These were previously being set at
# runtime by a KernelSU service script -- they belong in the build.
PRODUCT_PRODUCT_PROPERTIES += \
    ro.build.version.oplus.api=38 \
    ro.build.version.oplus.sub_api=48 \
    ro.build.version.oplusrom=V16.1.0 \
    ro.build.version.oplusrom.display=16.0.9 \
    ro.build.version.oplusrom.confidential=V16.1.0 \
    ro.build.version.ota=CPH2655_11.F.92_2920_202607071721

# Properties
PRODUCT_PRODUCT_PROPERTIES += \
    persist.vendor.camera.privapp.list=com.oplus.camera \
    ro.com.google.lens.oem_camera_package=com.oplus.camera \
    ro.com.google.lens.oem_image_package=com.oneplus.gallery \
    ro.oplus.camera.defercap.support=1 \
    ro.oplus.system.camera.name=com.oplus.camera \
    ro.oplus.camera.defercap.all.quick.visible.support=1 \
    ro.oplus.camera.livephoto.support=1 \
    ro.camera.disableHeicUltraHDR=1 \
    oplus.software.camera.10bit=1 \
    ro.oplus.camera.facing.front.need.disable.nfc=1 \
    ro.oplus.camera.portrait.center.switch=oplus.switch.portrait.center \
    ro.oplus.camera.portrait_center.prefix=oplus.portrait.center. \
    ro.oplus.camera.video.beauty.switch=oplus.switch.video.beauty \
    ro.oplus.camera.video_beauty.prefix=oplus.video.beauty. \
    ro.oplus.camera.speechassist=true \
    ro.oplus.system.camera.flashlight=com.oplus.motor.flashlight \
    ro.camera.privileged.3rdpartyApp=com.mediatek.expert.mtkcamhelper;com.aiunit.aon; \
    persist.logd.log.load.camerahalserver.lower_limit=1000 \
    persist.logd.log.load.camerahalserver.threshold=800000 \
    persist.logd.log.load.camerahalserver.upper_limit=3000 \
    persist.logd.log.load.com.oplus.camera.lower_limit=1000 \
    persist.logd.log.load.com.oplus.camera.threshold=800000 \
    persist.logd.log.load.com.oplus.camera.upper_limit=3000 \
    persist.logd.log.load.vendor.qti.camera.provider-service_64.lower_limit=500 \
    persist.logd.log.load.vendor.qti.camera.provider-service_64.threshold=400000 \
    persist.logd.log.load.vendor.qti.camera.provider-service_64.upper_limit=1500 \

# Photo
$(call soong_config_set,camera,package_name,com.oplus.packageName)
$(call soong_config_set,camera,allow_nonincreasing_timestamps,true)

# Video
$(call soong_config_set_bool,camera,override_format_from_reserved,true)


# AI / camera RRO overlays (prebuilt_overlay in overlays/Android.bp)
PRODUCT_PACKAGES += \
    aon.frameworkres.overlay.product \
    OplusAiConfigOverlayCommon \
    OplusCameraBigBallConfigOverlay

# SEpolicy
include vendor/oplus/camera/sepolicy/SEPolicy.mk

# Inherit from camera-vendor.mk
$(call inherit-product, vendor/oplus/camera/camera/camera-vendor.mk)
