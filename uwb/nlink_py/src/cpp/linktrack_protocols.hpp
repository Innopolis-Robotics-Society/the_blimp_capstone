// Non-ROS reimplementation of the thin glue layer from
// nooploop-dev/nlink_parser (src/utils/nlink_protocol.* and
// src/linktrack/protocols.*), BSD-3-Clause (c) Nooploop.
// Binds NProtocolExtracter frame slicing to the nlink_unpack C unpackers.
#ifndef LINKTRACK_PROTOCOLS_HPP
#define LINKTRACK_PROTOCOLS_HPP

#include <functional>

#include "protocol_extracter/nprotocol_base.h"

class NLinkProtocol : public NProtocolBase {
public:
  using NProtocolBase::NProtocolBase;

  void SetHandleDataCallback(std::function<void()> handle) {
    handle_data_callback_ = std::move(handle);
  }

protected:
  void HandleData(const uint8_t *data) final;
  // Returns the success flag of the underlying g_nlt_* UnpackData; the
  // callback only fires on success so stale singleton data is never emitted.
  virtual bool UnpackFrameData(const uint8_t *data) = 0;
  bool Verify(const uint8_t *data) override;

private:
  std::function<void()> handle_data_callback_;
};

class NLinkProtocolVLength : public NLinkProtocol {
public:
  using NLinkProtocol::NLinkProtocol;

protected:
  bool UpdateLength(const uint8_t *data, size_t available_bytes) override;
};

class ProtocolAnchorFrame0 : public NLinkProtocol {
public:
  ProtocolAnchorFrame0();

protected:
  bool UnpackFrameData(const uint8_t *data) override;
  bool Verify(const uint8_t *data) override;
};

class ProtocolTagFrame0 : public NLinkProtocol {
public:
  ProtocolTagFrame0();

protected:
  bool UnpackFrameData(const uint8_t *data) override;
};

#define NLINK_DECLARE_NODEFRAME_PROTOCOL(N)                                    \
  class ProtocolNodeFrame##N : public NLinkProtocolVLength {                   \
  public:                                                                      \
    ProtocolNodeFrame##N();                                                    \
                                                                               \
  protected:                                                                   \
    bool UnpackFrameData(const uint8_t *data) override;                        \
  };

NLINK_DECLARE_NODEFRAME_PROTOCOL(0)
NLINK_DECLARE_NODEFRAME_PROTOCOL(1)
NLINK_DECLARE_NODEFRAME_PROTOCOL(2)
NLINK_DECLARE_NODEFRAME_PROTOCOL(3)
NLINK_DECLARE_NODEFRAME_PROTOCOL(4)
NLINK_DECLARE_NODEFRAME_PROTOCOL(5)
NLINK_DECLARE_NODEFRAME_PROTOCOL(6)

#undef NLINK_DECLARE_NODEFRAME_PROTOCOL

#endif // LINKTRACK_PROTOCOLS_HPP
