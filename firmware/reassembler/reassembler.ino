

#define SEND_TO_PIXHAWK 0     // 0 = debug, 1 = send

#include <math.h>
#if SEND_TO_PIXHAWK
  #include <common/mavlink.h>
#endif

// ===== CONFIG =====
static const int NOSE_RX = 18, NOSE_TX = 17;   // UART1 <- TX носа
static const int TAIL_RX = 16, TAIL_TX = 15;   // UART2 <- TX кормы
static const uint32_t UWB_BAUD = 921600;
static const uint32_t PRINT_PERIOD_MS   = 500; // print in monitor

static const uint32_t COMPUTE_PERIOD_MS = 50;  // 20 Hz
static const bool  USE_EOP_GATE      = false;  // A-серия: eop часто всегда 2.55 -> выкл
static const float EOP_MAX_M         = 0.80f;
static const bool  USE_BASELINE_GATE = true;


static const float BASELINE_M        = 1;  // <<< real distance nose-tail
static const float BASELINE_TOL_M    = 0.40f;
static const uint32_t TAG_TIMEOUT_MS = 300;
static const float YAW_ALPHA         = 0.20f;
#if SEND_TO_PIXHAWK
static const int FC_RX = 5, FC_TX = 4;  
static const uint32_t FC_BAUD = 921600;
static const int32_t ORIGIN_LAT_E7 = 473000000; 
static const int32_t ORIGIN_LON_E7 =  85000000;
static const float   ORIGIN_ALT_M  = 400.0f;
static const uint8_t SYSID  = 1;
static const uint8_t COMPID = MAV_COMP_ID_VISUAL_INERTIAL_ODOMETRY;
#endif


class NlinkNode2 {
public:
  float x=0,y=0,z=0, eopx=9,eopy=9,eopz=9;
  uint32_t lastUpdateMs=0, count=0, raw=0, bad=0;
  bool valid=false;

  bool feed(uint8_t b){
    raw++;
    if(len_==0){ if(b!=0x55) return false; buf_[len_++]=b; return false; }
    if(len_==1){ if(b!=0x04){len_=0; return false;} buf_[len_++]=b; return false; }
    buf_[len_++]=b;
    if(len_==4){ expected_=buf_[2]|(buf_[3]<<8);
      if(expected_<24||expected_>(int)sizeof(buf_)){reset_();return false;} }
    if(expected_>0 && len_==expected_){ bool ok=parse_(); reset_(); return ok; }
    if(len_>=(int)sizeof(buf_)) reset_();
    return false;
  }
private:
  uint8_t buf_[256]; int len_=0; int expected_=-1;
  void reset_(){ len_=0; expected_=-1; }
  static int32_t i24_(const uint8_t*p){
    int32_t v=(int32_t)(p[0]|(p[1]<<8)|(p[2]<<16));
    if(v&0x00800000) v|=(int32_t)0xFF000000; return v;
  }
  bool parse_(){
    uint8_t s=0; for(int i=0;i<expected_-1;i++) s+=buf_[i];
    if(s!=buf_[expected_-1]){ bad++; return false; }
    eopx=buf_[10]/100.0f; eopy=buf_[11]/100.0f; eopz=buf_[12]/100.0f;
    x=i24_(&buf_[13])/1000.0f; y=i24_(&buf_[16])/1000.0f; z=i24_(&buf_[19])/1000.0f;
    lastUpdateMs=millis(); count++; valid=true; return true;
  }
};

//this is visione-estimation-type. Used to sent to FC to localize blimp
struct Packet { bool haveValues, ok; const char* skip; float N,E,D,yaw,dist; };


HardwareSerial uartNose(1);
HardwareSerial uartTail(2);
#if SEND_TO_PIXHAWK
HardwareSerial uartFC(0);
#endif
NlinkNode2 nose, tail;
float fcos=1, fsin=0; bool yawInit=false;
Packet g_last = {false,false,"старт",0,0,0,0,0};


static inline float ned_north(float ax,float ay,float az){ (void)ay;(void)az; return  ax; }
static inline float ned_east (float ax,float ay,float az){ (void)ax;(void)az; return  ay; }
static inline float ned_down (float ax,float ay,float az){ (void)ax;(void)ay; return -az; }


Packet computePacket(uint32_t now){
  Packet p = {false,false,"",0,0,0,0,0};
  bool fresh = nose.valid && tail.valid &&
               (now-nose.lastUpdateMs < TAG_TIMEOUT_MS) &&
               (now-tail.lastUpdateMs < TAG_TIMEOUT_MS);
  if(!fresh){ p.skip="нет свежих данных обоих тегов"; return p; }

  float dx=nose.x-tail.x, dy=nose.y-tail.y, dz=nose.z-tail.z;
  p.dist = sqrtf(dx*dx+dy*dy+dz*dz);
  float ax=0.5f*(nose.x+tail.x), ay=0.5f*(nose.y+tail.y), az=0.5f*(nose.z+tail.z);
  p.N=ned_north(ax,ay,az); p.E=ned_east(ax,ay,az); p.D=ned_down(ax,ay,az);

  float yawRaw = atan2f(ned_east(dx,dy,dz), ned_north(dx,dy,dz));
  if(!yawInit){ fcos=cosf(yawRaw); fsin=sinf(yawRaw); yawInit=true; }
  fcos=YAW_ALPHA*cosf(yawRaw)+(1-YAW_ALPHA)*fcos;
  fsin=YAW_ALPHA*sinf(yawRaw)+(1-YAW_ALPHA)*fsin;
  p.yaw = atan2f(fsin,fcos);
  p.haveValues = true;

  if(USE_EOP_GATE && (nose.eopx>EOP_MAX_M||nose.eopy>EOP_MAX_M||
                      tail.eopx>EOP_MAX_M||tail.eopy>EOP_MAX_M)){ p.skip="eop is so huge"; return p; }
  if(USE_BASELINE_GATE && fabsf(p.dist-BASELINE_M)>BASELINE_TOL_M){ p.skip="BASE error"; return p; }
  p.ok = true;
  return p;
}

void printTag(const char* name, NlinkNode2& t, uint32_t now){
  if(t.lastUpdateMs==0){ Serial.printf("[%s] NO DATA GODDAMN\n", name); return; }
  float hz = t.count*1000.0f/PRINT_PERIOD_MS;
  Serial.printf("[%s] x=%.3f y=%.3f z=%.3f  eop=%.2f/%.2f/%.2f  %.0f Hz  raw=%lu bad=%lu%s\n",
                name, t.x,t.y,t.z, t.eopx,t.eopy,t.eopz, hz,
                (unsigned long)t.raw, (unsigned long)t.bad,
                (now-t.lastUpdateMs>500)?"  (STALE)":"");
  t.count=0; t.raw=0; t.bad=0;
}

void printPacket(const Packet& g){
  if(!g.haveValues){ Serial.printf("[PKT]  нет данных: %s\n", g.skip); return; }
  if(g.ok)
    Serial.printf("[PKT]  N=%.2f E=%.2f D=%.2f  yaw=%.0f deg  dist=%.2f  -> SEND%s\n",
                  g.N,g.E,g.D, g.yaw*57.2958f, g.dist, SEND_TO_PIXHAWK?" sent":"preview");
  else
    Serial.printf("[PKT]  N=%.2f E=%.2f D=%.2f  yaw=%.0f deg  dist=%.2f  -> SKIP (%s)\n",
                  g.N,g.E,g.D, g.yaw*57.2958f, g.dist, g.skip);
}

#if SEND_TO_PIXHAWK
void sendBuf(mavlink_message_t& m){
  static uint8_t out[MAVLINK_MAX_PACKET_LEN];
  uint16_t n = mavlink_msg_to_send_buffer(out,&m); uartFC.write(out,n);
}
void sendSetOrigin(){
  mavlink_message_t m;
  mavlink_msg_set_gps_global_origin_pack(SYSID,COMPID,&m, 1,
      ORIGIN_LAT_E7, ORIGIN_LON_E7, (int32_t)(ORIGIN_ALT_M*1000.0f), (uint64_t)micros());
  sendBuf(m);
}
void sendHeartbeat(){
  mavlink_message_t m;
  mavlink_msg_heartbeat_pack(SYSID,COMPID,&m, MAV_TYPE_ONBOARD_CONTROLLER,
      MAV_AUTOPILOT_INVALID, 0,0, MAV_STATE_ACTIVE);
  sendBuf(m);
}
void sendVision(float N,float E,float D,float yaw){
  mavlink_message_t m; float cov[21]; cov[0]=NAN;
  mavlink_msg_vision_position_estimate_pack(SYSID,COMPID,&m, (uint64_t)micros(),
      N,E,D, 0.0f,0.0f,yaw, cov, 0);
  sendBuf(m);
}
#endif

void setup(){
  Serial.begin(115200);
  uartNose.setRxBufferSize(2048);
  uartTail.setRxBufferSize(2048);
  uartNose.begin(UWB_BAUD, SERIAL_8N1, NOSE_RX, NOSE_TX);
  uartTail.begin(UWB_BAUD, SERIAL_8N1, TAIL_RX, TAIL_TX);
#if SEND_TO_PIXHAWK
  uartFC.begin(FC_BAUD, SERIAL_8N1, FC_RX, FC_TX);
  Serial.println("bridge: SEND mode (origin шлётся периодически)");
#else
  Serial.println("bridge: PREVIEW mode (MAVLink не шлётся)");
#endif
}

void loop(){
  while(uartNose.available()) nose.feed((uint8_t)uartNose.read());
  while(uartTail.available()) tail.feed((uint8_t)uartTail.read());

  uint32_t now = millis();

  static uint32_t lastCompute=0;
  if(now-lastCompute >= COMPUTE_PERIOD_MS){
    lastCompute = now;
    g_last = computePacket(now);
#if SEND_TO_PIXHAWK
    static uint32_t lastOrigin=0;
    if(now-lastOrigin>=3000){ lastOrigin=now; sendSetOrigin(); }   
    static uint32_t lastHb=0;
    if(now-lastHb>=1000){ lastHb=now; sendHeartbeat(); }
    if(g_last.ok) sendVision(g_last.N, g_last.E, g_last.D, g_last.yaw);
#endif
  }

  static uint32_t lastPrint=0;
  if(now-lastPrint >= PRINT_PERIOD_MS){
    lastPrint = now;
    printTag("NOSE", nose, now);
    printTag("TAIL", tail, now);
    printPacket(g_last);
  }
}