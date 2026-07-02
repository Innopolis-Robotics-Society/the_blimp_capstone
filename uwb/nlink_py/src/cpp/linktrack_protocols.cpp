#include "linktrack_protocols.hpp"

#include <numeric>

#include "nlink_unpack/nlink_linktrack_anchorframe0.h"
#include "nlink_unpack/nlink_linktrack_nodeframe0.h"
#include "nlink_unpack/nlink_linktrack_nodeframe1.h"
#include "nlink_unpack/nlink_linktrack_nodeframe2.h"
#include "nlink_unpack/nlink_linktrack_nodeframe3.h"
#include "nlink_unpack/nlink_linktrack_nodeframe4.h"
#include "nlink_unpack/nlink_linktrack_nodeframe5.h"
#include "nlink_unpack/nlink_linktrack_nodeframe6.h"
#include "nlink_unpack/nlink_linktrack_tagframe0.h"

void NLinkProtocol::HandleData(const uint8_t *data) {
  if (UnpackFrameData(data) && handle_data_callback_) {
    handle_data_callback_();
  }
}

bool NLinkProtocol::Verify(const uint8_t *data) {
  uint8_t sum = 0;
  return data[length() - 1] ==
         std::accumulate(data, data + length() - sizeof(sum), sum);
}

bool NLinkProtocolVLength::UpdateLength(const uint8_t *data,
                                        size_t available_bytes) {
  if (available_bytes < 4)
    return false;
  return set_length(static_cast<size_t>(data[2] | data[3] << 8));
}

ProtocolAnchorFrame0::ProtocolAnchorFrame0()
    : NLinkProtocol(
          true, nlt_anchorframe0_.fixed_part_size,
          {nlt_anchorframe0_.frame_header, nlt_anchorframe0_.function_mark},
          {nlt_anchorframe0_.tail_check}) {}

bool ProtocolAnchorFrame0::UnpackFrameData(const uint8_t *data) {
  return nlt_anchorframe0_.UnpackData(data, length());
}

bool ProtocolAnchorFrame0::Verify(const uint8_t *data) {
  return data[length() - 1] == nlt_anchorframe0_.tail_check;
}

ProtocolTagFrame0::ProtocolTagFrame0()
    : NLinkProtocol(
          true, g_nlt_tagframe0.fixed_part_size,
          {g_nlt_tagframe0.frame_header, g_nlt_tagframe0.function_mark}) {}

bool ProtocolTagFrame0::UnpackFrameData(const uint8_t *data) {
  return g_nlt_tagframe0.UnpackData(data, length());
}

#define NLINK_DEFINE_NODEFRAME_PROTOCOL(N)                                     \
  ProtocolNodeFrame##N::ProtocolNodeFrame##N()                                 \
      : NLinkProtocolVLength(true, g_nlt_nodeframe##N.fixed_part_size,         \
                             {g_nlt_nodeframe##N.frame_header,                 \
                              g_nlt_nodeframe##N.function_mark}) {}            \
                                                                               \
  bool ProtocolNodeFrame##N::UnpackFrameData(const uint8_t *data) {            \
    return g_nlt_nodeframe##N.UnpackData(data, length());                      \
  }

NLINK_DEFINE_NODEFRAME_PROTOCOL(0)
NLINK_DEFINE_NODEFRAME_PROTOCOL(1)
NLINK_DEFINE_NODEFRAME_PROTOCOL(2)
NLINK_DEFINE_NODEFRAME_PROTOCOL(3)
NLINK_DEFINE_NODEFRAME_PROTOCOL(4)
NLINK_DEFINE_NODEFRAME_PROTOCOL(5)
NLINK_DEFINE_NODEFRAME_PROTOCOL(6)

#undef NLINK_DEFINE_NODEFRAME_PROTOCOL
