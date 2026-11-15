/* SPDX-License-Identifier: GPL-2.0-only
 * BGRx copy into a downstream video pool. Optional non-temporal SSE2 stores
 * avoid read-for-ownership traffic when the destination is display memory.
 */
#include <gst/gst.h>
#include <gst/video/gstvideofilter.h>
#include <string.h>
#if defined(__SSE2__)
#include <emmintrin.h>
#endif

typedef struct { GstVideoFilter parent; gboolean streaming_stores; gboolean reported; } GstImacCopy;
typedef struct { GstVideoFilterClass parent_class; } GstImacCopyClass;
G_DEFINE_TYPE(GstImacCopy, gst_imac_copy, GST_TYPE_VIDEO_FILTER)
enum { PROP_0, PROP_STREAMING_STORES };

static void copy_streaming(guint8 *dest, const guint8 *src, gsize size) {
#if defined(__SSE2__)
    while (size && ((guintptr)dest & 15)) { *dest++ = *src++; --size; }
    while (size >= 64) {
        __m128i a = _mm_loadu_si128((const __m128i *)(src));
        __m128i b = _mm_loadu_si128((const __m128i *)(src+16));
        __m128i c = _mm_loadu_si128((const __m128i *)(src+32));
        __m128i d = _mm_loadu_si128((const __m128i *)(src+48));
        _mm_stream_si128((__m128i *)(dest), a);
        _mm_stream_si128((__m128i *)(dest+16), b);
        _mm_stream_si128((__m128i *)(dest+32), c);
        _mm_stream_si128((__m128i *)(dest+48), d);
        dest += 64; src += 64; size -= 64;
    }
#endif
    memcpy(dest, src, size);
}

static GstFlowReturn transform(GstVideoFilter *filter, GstVideoFrame *in, GstVideoFrame *out) {
    GstImacCopy *self = (GstImacCopy *)filter;
    if (!self->reported) {
        GstMemory *mem = gst_buffer_peek_memory(out->buffer, 0);
        g_printerr("imaccopy: %dx%d input-stride=%d output-stride=%d output-memory=%s streaming-stores=%d\n",
            GST_VIDEO_FRAME_WIDTH(in), GST_VIDEO_FRAME_HEIGHT(in),
            GST_VIDEO_FRAME_PLANE_STRIDE(in, 0), GST_VIDEO_FRAME_PLANE_STRIDE(out, 0),
            mem && mem->allocator ? mem->allocator->mem_type : "unknown", self->streaming_stores);
        self->reported = TRUE;
    }
    guint width = GST_VIDEO_FRAME_WIDTH(in), height = GST_VIDEO_FRAME_HEIGHT(in);
    gint ss = GST_VIDEO_FRAME_PLANE_STRIDE(in, 0), ds = GST_VIDEO_FRAME_PLANE_STRIDE(out, 0);
    if (!self->streaming_stores || GST_VIDEO_FRAME_FORMAT(in) != GST_VIDEO_FORMAT_BGRx ||
        GST_VIDEO_FRAME_FORMAT(out) != GST_VIDEO_FORMAT_BGRx ||
        GST_VIDEO_FRAME_WIDTH(out) != (gint)width || GST_VIDEO_FRAME_HEIGHT(out) != (gint)height ||
        ss < 0 || ds < 0 || (gsize)ss < (gsize)width*4 || (gsize)ds < (gsize)width*4) {
        return gst_video_frame_copy(out, in) ? GST_FLOW_OK : GST_FLOW_ERROR;
    }
    for (guint y = 0; y < height; y++) {
        copy_streaming((guint8 *)GST_VIDEO_FRAME_PLANE_DATA(out, 0) + (gsize)y*ds,
            (const guint8 *)GST_VIDEO_FRAME_PLANE_DATA(in, 0) + (gsize)y*ss, (gsize)width*4);
    }
#if defined(__SSE2__)
    /* Complete non-temporal writes before the buffer is submitted to KMS. */
    _mm_sfence();
#endif
    return GST_FLOW_OK;
}
static void set_property(GObject *object, guint prop, const GValue *value, GParamSpec *spec) {
    if (prop == PROP_STREAMING_STORES) ((GstImacCopy *)object)->streaming_stores = g_value_get_boolean(value);
    else G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop, spec);
}
static void get_property(GObject *object, guint prop, GValue *value, GParamSpec *spec) {
    if (prop == PROP_STREAMING_STORES) g_value_set_boolean(value, ((GstImacCopy *)object)->streaming_stores);
    else G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop, spec);
}
static void gst_imac_copy_class_init(GstImacCopyClass *klass) {
    GstElementClass *element = GST_ELEMENT_CLASS(klass);
    GObjectClass *object = G_OBJECT_CLASS(klass);
    object->set_property = set_property; object->get_property = get_property;
    g_object_class_install_property(object, PROP_STREAMING_STORES,
        g_param_spec_boolean("streaming-stores", "Streaming stores", "Use SSE2 streaming stores when built for x86; otherwise memcpy",
            FALSE, G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS | GST_PARAM_MUTABLE_READY));
    GstCaps *caps = gst_caps_from_string("video/x-raw,format=BGRx,width=[1,32767],height=[1,32767],framerate=[0/1,2147483647/1]");
    gst_element_class_add_pad_template(element, gst_pad_template_new("sink", GST_PAD_SINK, GST_PAD_ALWAYS, caps));
    gst_element_class_add_pad_template(element, gst_pad_template_new("src", GST_PAD_SRC, GST_PAD_ALWAYS, caps));
    gst_caps_unref(caps);
    gst_element_class_set_static_metadata(element, "iMac display buffer copy", "Filter/Video",
        "Copy BGRx to the downstream pool with optional streaming stores", "iMac Receiver project");
    GST_BASE_TRANSFORM_CLASS(klass)->passthrough_on_same_caps = FALSE;
    GST_VIDEO_FILTER_CLASS(klass)->transform_frame = transform;
}
static void gst_imac_copy_init(GstImacCopy *self) {
    self->streaming_stores = FALSE; self->reported = FALSE;
    gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), FALSE);
    gst_base_transform_set_passthrough(GST_BASE_TRANSFORM(self), FALSE);
}
static gboolean plugin_init(GstPlugin *plugin) {
    return gst_element_register(plugin, "imaccopy", GST_RANK_NONE, gst_imac_copy_get_type());
}
#define PACKAGE "imac-display-receiver"
GST_PLUGIN_DEFINE(GST_VERSION_MAJOR, GST_VERSION_MINOR, imaccopy,
    "iMac receiver BGRx copy", plugin_init, "0.1", "GPL", PACKAGE,
    "https://gstreamer.freedesktop.org/")
