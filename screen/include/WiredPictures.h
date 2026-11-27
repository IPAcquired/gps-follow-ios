#pragma once
#include <TFT_eSPI.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "WiredDesktopProtocol.h"

// The ESP32 ROM implements baseline JPEG and miniz. Its sizable Huffman state
// belongs on the heap, never on the Arduino loop stack. JPEG and tiles use the
// same buffers and cannot interleave, except for authenticated heartbeats.
#ifdef ARDUINO_ARCH_ESP32
#include <esp_rom_tjpgd.h>

#else
#include <vector>
#include <jpeglib.h>
#include <setjmp.h>
#endif

#include "PictureStorage.h"
class WiredPictures {
 public:
  enum { MaxJpeg=16384, MaxTile=4128, MaxPixels=2048 };
  uint32_t tiles=0, frames=0, failures=0, receiveMs=0, commitMs=0;
  void reserve(){storageOK_=picturestore::selfTest();}
  void acquire(){
    if(!storageOK_)return;
    new(&picturestore::shared.decoder) picturestore::Scratch{};
    work_=&picturestore::shared.decoder;
  }
  void clearView(){cancel();picturestore::wipe();if(work_)memset(work_,0,sizeof(*work_));}
  void release(){
    clearView();
    if(work_){work_=nullptr;new(&picturestore::shared.menus) picturestore::Menus{};}
  }
  unsigned flags()const{return storageOK_?5:0;}
  bool reserved()const{return storageOK_;}
  void cancel(){kind_=0;expected_=received_=0;}
  bool busy()const{return kind_!=0;}
  bool receivingJpeg()const{return kind_==9;}
  bool record(TFT_eSPI& lcd,const uint8_t* b,size_t n,unsigned visible,uint32_t& pixelCount,uint32_t& paintCount,bool (*guard)()){
    using namespace wireddesktop;
    bool ok=false;
    if(b[0]==6&&n==11&&!busy()&&work_){
      x_=get16(b+1);y_=get16(b+3);w_=get16(b+5);h_=get16(b+7);expected_=get16(b+9);
      ok=w_&&h_&&uint32_t(w_)*h_<=MaxPixels&&uint32_t(x_)+w_<=Width&&uint32_t(y_)+h_<=Height&&expected_&&expected_<=MaxTile;
      if(ok){kind_=6;received_=0;}
    }else if(b[0]==9&&(n==11||n==3)&&!busy()&&(flags()&4)){
      expected_=get16(b+1);checkCrc_=n==11;
      ok=expected_>=4&&expected_<=MaxJpeg&&(!checkCrc_||(get16(b+3)==Width&&get16(b+5)==Height));
      if(ok){if(checkCrc_)crc_=uint32_t(b[7])<<24|uint32_t(b[8])<<16|uint32_t(b[9])<<8|b[10];
        kind_=9;received_=0;began_=millis();}
    }else if((b[0]==7||b[0]==10)&&kind_+1==b[0]&&n>=4&&n<=40&&get16(b+1)==received_&&n-3<=expected_-received_){
      picturestore::write(received_,b+3,n-3);received_+=n-3;ok=true;
      if(kind_==6&&received_==expected_){
        ok=inflateTile();
        if(ok){unsigned rows=clipped(y_,h_,visible);
          if(rows){unsigned count=w_*rows;for(unsigned i=0;i<count;i++)work_->tile.out[i]=get16(reinterpret_cast<uint8_t*>(work_->tile.out)+2*i);
            lcd.setAddrWindow(x_,y_,w_,rows);lcd.pushColors(work_->tile.out,count,true);pixelCount+=count;++paintCount;}
          ++tiles;}
        cancel();
      }
    }else if(b[0]==11&&n==1&&kind_==9&&received_==expected_){
      receiveMs=millis()-began_;uint32_t start=millis();
      ok=picturestore::byte(0)==0xff&&picturestore::byte(1)==0xd8&&picturestore::byte(expected_-2)==0xff&&picturestore::byte(expected_-1)==0xd9&&(!checkCrc_||checksum32(expected_)==crc_);
      if(ok)ok=jpeg(lcd,visible,guard);
      if(ok){pixelCount+=uint32_t(Width)*visible;++paintCount;++frames;}
      commitMs=millis()-start;cancel();
    }
    if(!ok){++failures;cancel();}
    return ok;
  }
  static unsigned clipped(unsigned y,unsigned h,unsigned edge){return y>=edge?0:(h>edge-y?edge-y:h);}
 private:
  bool storageOK_=false;
  uint8_t kind_=0;picturestore::Scratch* work_=nullptr;
  size_t expected_=0,received_=0;
  unsigned x_=0,y_=0,w_=0,h_=0;bool checkCrc_=false;
  uint32_t crc_=0,began_=0;
  static uint32_t checksum32(size_t n){
    uint32_t c=~uint32_t(0);for(size_t i=0;i<n;i++){c^=picturestore::byte(i);for(int bit=0;bit<8;bit++)c=c&1?(c>>1)^0xedb88320u:c>>1;}return ~c;
  }
  static int readDeflate(uzlib_uncomp* engine){
    auto* r=reinterpret_cast<picturestore::InflateReader*>(engine);
    return r->pos<r->end?picturestore::byte(r->pos++):-1;
  }
  bool inflateTile(){
    auto& r=work_->tile.input;r={};r.end=received_;auto& d=r.engine;
    uzlib_uncompress_init(&d,nullptr,0);d.source_read_cb=readDeflate;
    auto* raw=reinterpret_cast<uint8_t*>(work_->tile.out);d.dest_start=raw;d.dest=raw;
    // One extra byte detects oversized output before it can reach the panel.
    d.dest_limit=raw+2*w_*h_+1;
    return uzlib_zlib_parse_header(&d)>=0&&uzlib_uncompress_chksum(&d)==TINF_DONE&&
      !d.eof&&d.dest==raw+2*w_*h_&&r.pos==received_;
  }
  static uint16_t color(const uint8_t* rgb){return ((rgb[0]&248)<<8)|((rgb[1]&252)<<3)|(rgb[2]>>3);}
#ifdef ARDUINO_ARCH_ESP32
  struct Draw{WiredPictures* self;TFT_eSPI* lcd;size_t pos;unsigned edge;uint32_t checkAt;bool (*guard)();};
  static uint32_t readJpeg(esp_rom_tjpgd_dec_t* d,uint8_t* dest,uint32_t n){
    auto& a=*static_cast<Draw*>(d->device);size_t left=a.self->received_-a.pos;if(n>left)n=left;
    if(dest)picturestore::read(a.pos,dest,n);a.pos+=n;return n;
  }
  static uint32_t drawBlock(esp_rom_tjpgd_dec_t* d,void* buf,esp_rom_tjpgd_rect_t* r){
    auto& a=*static_cast<Draw*>(d->device);unsigned w=r->right-r->left+1,h=r->bottom-r->top+1;
    if(r->right>=480||r->bottom>=296||!w||!h||w*h>256)return 0;
    if(a.guard&&uint32_t(millis()-a.checkAt)>=24){a.checkAt=millis();if(!a.guard())return 0;}
    unsigned rows=clipped(r->top,h,a.edge);if(!a.lcd||!rows)return 1;
    auto* rgb=static_cast<uint8_t*>(buf);auto* out=a.self->work_->jpeg.colors;
    for(unsigned i=0;i<w*rows;i++)out[i]=color(rgb+3*i);
    a.lcd->setAddrWindow(r->left,r->top,w,rows);a.lcd->pushColors(out,w*rows,true);return 1;
  }
  bool jpeg(TFT_eSPI& lcd,unsigned edge,bool (*guard)()){
    // Fully validate the compressed entropy before altering the previous image.
    Draw ctx{this,nullptr,0,edge,millis(),guard};
    for(unsigned pass=0;pass<2;pass++){
      if(guard&&!guard())return false;
      esp_rom_tjpgd_dec_t d{};ctx.pos=0;ctx.lcd=pass?&lcd:nullptr;
      if(esp_rom_tjpgd_prepare(&d,readJpeg,work_->jpeg.pool,sizeof work_->jpeg.pool,&ctx)!=JDR_OK||d.width!=480||d.height!=296||d.msx>2||d.msy>2)return false;
      if(pass)lcd.startWrite();
      bool ok=esp_rom_tjpgd_decomp(&d,drawBlock,0)==JDR_OK;
      if(pass)lcd.endWrite();
      if(!ok)return false;
    }
    return !guard||guard();
  }
#else
  struct JError{jpeg_error_mgr err;jmp_buf env;};
  static void jpegError(j_common_ptr info){longjmp(reinterpret_cast<JError*>(info->err)->env,1);}
  bool jpeg(TFT_eSPI& lcd,unsigned edge,bool (*guard)()){
    jpeg_decompress_struct d{};JError err{};d.err=jpeg_std_error(&err.err);err.err.error_exit=jpegError;
    if(setjmp(err.env)){jpeg_destroy_decompress(&d);return false;}jpeg_create_decompress(&d);
    std::vector<uint8_t> contiguous(received_);picturestore::read(0,contiguous.data(),received_);
    jpeg_mem_src(&d,contiguous.data(),received_);bool ok=jpeg_read_header(&d,TRUE)==JPEG_HEADER_OK&&d.image_width==480&&d.image_height==296&&!d.progressive_mode;
    if(ok){d.out_color_space=JCS_RGB;jpeg_start_decompress(&d);uint8_t row[480*3];JSAMPROW p=row;
      while(d.output_scanline<d.output_height){unsigned y=d.output_scanline;
        if((guard&&!guard())||jpeg_read_scanlines(&d,&p,1)!=1){ok=false;break;}
        if(y<edge){for(unsigned x=0;x<480;x++)work_->tile.out[x]=color(row+3*x);lcd.setAddrWindow(0,y,480,1);lcd.pushColors(work_->tile.out,480,true);}}
      if(ok)jpeg_finish_decompress(&d);}
    jpeg_destroy_decompress(&d);return ok;
  }
#endif
};
