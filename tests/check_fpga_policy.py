#!/usr/bin/env python3
# Compile actual pure validation functions from original and patched sources.
# This tests policy scope, not FPGA hardware programming or image correctness.
import pathlib,re,subprocess,tempfile
root=pathlib.Path(__file__).resolve().parents[1]
header=(root/'vendor/gc555/gc555.h').read_text()
original=(root/'vendor/gc555/gc555-fpga.c').read_text()
def function(source,start):
    brace=source.index('{',start);depth=1;i=brace+1
    while depth:
        depth += (source[i]=='{')-(source[i]=='}');i+=1
    return source[start:i]+'\n'
def generate(source,patched):
    code='#include <stdbool.h>\n#include <stdint.h>\n#include <errno.h>\n#include <assert.h>\ntypedef uint32_t u32;\n'
    code+='\n'.join(re.findall(r'enum gc555_video_\w+\s*\{[^}]*\};',header,re.S))
    code+='\n'+re.search(r'struct gc555_fpga_video_config \{.*?\n\};',source,re.S).group()
    code+='\n'+ '\n'.join(re.findall(r'^#define GC555_FPGA_(?:MAX_WIDTH|MAX_HEIGHT|RGB_TO_YUV_\w+)\s+\d+U',source,re.M))+'\n'
    for m in re.finditer(r'^static bool\b',source,re.M):code+=function(source,m.start())
    code+=function(source,source.rfind('static int',0,source.index('gc555_fpga_validate_config(')))
    code+=function(source,source.rfind('static u32',0,source.index('gc555_fpga_rgb_to_yuv_selector(')))
    code+='''
int main(void) {
 struct gc555_fpga_video_config b={
 .input_width=3840,.input_height=2160,.output_width=3840,.output_height=2160,
 .input_frame_rate_hz=30,.output_frame_rate_hz=30,.input_class=GC555_VIDEO_INPUT_UHD,
 .input_encoding=GC555_VIDEO_ENCODING_RGB_LIMITED,.input_sampling=GC555_VIDEO_SAMPLING_RGB,
 .input_colorimetry=GC555_VIDEO_COLORIMETRY_BT709,.input_hdr_mode=GC555_VIDEO_HDR_SDR,
 .output_format=GC555_VIDEO_FORMAT_YUYV,.dual_pixel=true,.ddr=true};
 struct gc555_fpga_video_config c=b;
'''
    code+=f'assert(gc555_fpga_validate_config(&b)=={0 if patched else "-EOPNOTSUPP"});\n'
    code+='''
 assert(gc555_fpga_rgb_to_yuv_selector(&b)==GC555_FPGA_RGB_TO_YUV_BT709_LIMITED);
 c=b;c.input_encoding=GC555_VIDEO_ENCODING_RGB_FULL;assert(gc555_fpga_validate_config(&c)==0);
 assert(gc555_fpga_rgb_to_yuv_selector(&c)==GC555_FPGA_RGB_TO_YUV_BT709_FULL);
 c=b;c.input_frame_rate_hz=c.output_frame_rate_hz=60;assert(gc555_fpga_validate_config(&c)==-EOPNOTSUPP);
 c=b;c.dual_pixel=false;assert(gc555_fpga_validate_config(&c)==-EOPNOTSUPP);
 c=b;c.ddr=false;assert(gc555_fpga_validate_config(&c)==-EOPNOTSUPP);
 c=b;c.input_hdr_mode=GC555_VIDEO_HDR_PQ;assert(gc555_fpga_validate_config(&c)==-EOPNOTSUPP);
 c=b;c.input_colorimetry=GC555_VIDEO_COLORIMETRY_BT2020;assert(gc555_fpga_validate_config(&c)==-EOPNOTSUPP);
 c=b;c.output_format=GC555_VIDEO_FORMAT_RGB32;assert(gc555_fpga_validate_config(&c)==-EOPNOTSUPP);
 c=b;c.output_format=GC555_VIDEO_FORMAT_NV12;assert(gc555_fpga_validate_config(&c)==-EOPNOTSUPP);
 c=b;c.output_width=1920;assert(gc555_fpga_validate_config(&c)==-EOPNOTSUPP);
 c=b;c.input_width=c.output_width=1920;c.input_height=c.output_height=1080;
 c.input_frame_rate_hz=c.output_frame_rate_hz=60;c.input_encoding=GC555_VIDEO_ENCODING_RGB_FULL;
 c.input_class=GC555_VIDEO_INPUT_HD;c.dual_pixel=false;c.ddr=false;c.output_format=GC555_VIDEO_FORMAT_NV12;
 assert(gc555_fpga_validate_config(&c)==0);
 return 0;
}
'''
    return code
with tempfile.TemporaryDirectory() as d:
    d=pathlib.Path(d);(d/'gc555-fpga.c').write_text(original)
    subprocess.run(['patch','-d',str(d),'-p1','-i',str(root/'patches/0003-native-4k30-limited-rgb.patch')],check=True)
    for name,source,patched in [('original',original,False),('patched',(d/'gc555-fpga.c').read_text(),True)]:
        p=d/(name+'.c');p.write_text(generate(source,patched))
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Wno-unused-function',str(p),'-o',str(d/name)],check=True)
        subprocess.run([str(d/name)],check=True);print(name+': policy and BT709 matrix selection checks PASS')
