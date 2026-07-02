// pybind11 module exposing the Nooploop LinkTrack NLink stream parser.
// Frame slicing and unpacking are done by the untouched upstream code
// (protocol_extracter + nlink_unpack); this file only converts the
// unpacked g_nlt_* singletons into Python dicts.
#include <pybind11/pybind11.h>

#include <memory>
#include <string>
#include <vector>

#include "linktrack_protocols.hpp"
#include "nlink_unpack/nlink_linktrack_anchorframe0.h"
#include "nlink_unpack/nlink_linktrack_nodeframe0.h"
#include "nlink_unpack/nlink_linktrack_nodeframe1.h"
#include "nlink_unpack/nlink_linktrack_nodeframe2.h"
#include "nlink_unpack/nlink_linktrack_nodeframe3.h"
#include "nlink_unpack/nlink_linktrack_nodeframe4.h"
#include "nlink_unpack/nlink_linktrack_nodeframe5.h"
#include "nlink_unpack/nlink_linktrack_nodeframe6.h"
#include "nlink_unpack/nlink_linktrack_tagframe0.h"
#include "protocol_extracter/nprotocol_extracter.h"

namespace py = pybind11;

namespace {

template <typename T, size_t N> py::list ToList(const T (&arr)[N]) {
  py::list out;
  for (size_t i = 0; i < N; ++i) {
    out.append(arr[i]);
  }
  return out;
}

py::dict AnchorFrame0ToDict() {
  const auto &r = nlt_anchorframe0_.result;
  py::list nodes;
  for (size_t i = 0; i < r.valid_node_count; ++i) {
    const auto *n = r.nodes[i];
    nodes.append(py::dict(
        py::arg("role") = static_cast<int>(n->role), py::arg("id") = n->id,
        py::arg("pos_3d") = ToList(n->pos_3d),
        py::arg("dis_arr") = ToList(n->dis_arr)));
  }
  return py::dict(
      py::arg("role") = static_cast<int>(r.role), py::arg("id") = r.id,
      py::arg("local_time") = r.local_time,
      py::arg("system_time") = r.system_time, py::arg("voltage") = r.voltage,
      py::arg("nodes") = nodes);
}

py::dict TagFrame0ToDict() {
  const auto &r = g_nlt_tagframe0.result;
  return py::dict(
      py::arg("role") = static_cast<int>(r.role), py::arg("id") = r.id,
      py::arg("pos_3d") = ToList(r.pos_3d), py::arg("eop_3d") = ToList(r.eop_3d),
      py::arg("vel_3d") = ToList(r.vel_3d),
      py::arg("dis_arr") = ToList(r.dis_arr),
      py::arg("imu_gyro_3d") = ToList(r.imu_gyro_3d),
      py::arg("imu_acc_3d") = ToList(r.imu_acc_3d),
      py::arg("angle_3d") = ToList(r.angle_3d),
      py::arg("quaternion") = ToList(r.quaternion),
      py::arg("local_time") = r.local_time,
      py::arg("system_time") = r.system_time, py::arg("voltage") = r.voltage);
}

py::dict NodeFrame0ToDict() {
  const auto &r = g_nlt_nodeframe0.result;
  py::list nodes;
  for (size_t i = 0; i < r.valid_node_count; ++i) {
    const auto *n = r.nodes[i];
    nodes.append(py::dict(
        py::arg("role") = static_cast<int>(n->role), py::arg("id") = n->id,
        py::arg("data") = py::bytes(reinterpret_cast<const char *>(n->data),
                                    n->data_length)));
  }
  return py::dict(py::arg("role") = static_cast<int>(r.role),
                  py::arg("id") = r.id, py::arg("nodes") = nodes);
}

py::dict NodeFrame1ToDict() {
  const auto &r = g_nlt_nodeframe1.result;
  py::list nodes;
  for (size_t i = 0; i < r.valid_node_count; ++i) {
    const auto *n = r.nodes[i];
    nodes.append(py::dict(py::arg("role") = static_cast<int>(n->role),
                          py::arg("id") = n->id,
                          py::arg("pos_3d") = ToList(n->pos_3d)));
  }
  return py::dict(
      py::arg("role") = static_cast<int>(r.role), py::arg("id") = r.id,
      py::arg("local_time") = r.local_time,
      py::arg("system_time") = r.system_time, py::arg("voltage") = r.voltage,
      py::arg("nodes") = nodes);
}

py::dict NodeFrame2ToDict() {
  const auto &r = g_nlt_nodeframe2.result;
  py::list nodes;
  for (size_t i = 0; i < r.valid_node_count; ++i) {
    const auto *n = r.nodes[i];
    nodes.append(py::dict(
        py::arg("role") = static_cast<int>(n->role), py::arg("id") = n->id,
        py::arg("dis") = n->dis, py::arg("fp_rssi") = n->fp_rssi,
        py::arg("rx_rssi") = n->rx_rssi));
  }
  return py::dict(
      py::arg("role") = static_cast<int>(r.role), py::arg("id") = r.id,
      py::arg("pos_3d") = ToList(r.pos_3d), py::arg("eop_3d") = ToList(r.eop_3d),
      py::arg("vel_3d") = ToList(r.vel_3d),
      py::arg("angle_3d") = ToList(r.angle_3d),
      py::arg("quaternion") = ToList(r.quaternion),
      py::arg("imu_gyro_3d") = ToList(r.imu_gyro_3d),
      py::arg("imu_acc_3d") = ToList(r.imu_acc_3d),
      py::arg("local_time") = r.local_time,
      py::arg("system_time") = r.system_time, py::arg("voltage") = r.voltage,
      py::arg("nodes") = nodes);
}

template <typename Result> py::dict RangingFrameToDict(const Result &r) {
  py::list nodes;
  for (size_t i = 0; i < r.valid_node_count; ++i) {
    const auto *n = r.nodes[i];
    nodes.append(py::dict(
        py::arg("role") = static_cast<int>(n->role), py::arg("id") = n->id,
        py::arg("dis") = n->dis, py::arg("fp_rssi") = n->fp_rssi,
        py::arg("rx_rssi") = n->rx_rssi));
  }
  return py::dict(
      py::arg("role") = static_cast<int>(r.role), py::arg("id") = r.id,
      py::arg("local_time") = r.local_time,
      py::arg("system_time") = r.system_time, py::arg("voltage") = r.voltage,
      py::arg("nodes") = nodes);
}

py::dict NodeFrame3ToDict() {
  return RangingFrameToDict(g_nlt_nodeframe3.result);
}

py::dict NodeFrame4ToDict() {
  const auto &r = g_nlt_nodeframe4.result;
  py::list tags;
  for (size_t i = 0; i < r.tag_count; ++i) {
    const auto *tag = r.tags[i];
    py::list anchors;
    for (size_t j = 0; j < tag->anchor_count; ++j) {
      anchors.append(py::dict(py::arg("id") = tag->anchors[j]->id,
                              py::arg("dis") = tag->anchors[j]->dis));
    }
    tags.append(py::dict(py::arg("id") = tag->id,
                         py::arg("voltage") = tag->voltage,
                         py::arg("anchors") = anchors));
  }
  return py::dict(
      py::arg("role") = static_cast<int>(r.role), py::arg("id") = r.id,
      py::arg("local_time") = r.local_time,
      py::arg("system_time") = r.system_time, py::arg("voltage") = r.voltage,
      py::arg("tags") = tags);
}

py::dict NodeFrame5ToDict() {
  return RangingFrameToDict(g_nlt_nodeframe5.result);
}

py::dict NodeFrame6ToDict() {
  const auto &r = g_nlt_nodeframe6.result;
  py::list nodes;
  for (size_t i = 0; i < r.valid_node_count; ++i) {
    const auto *n = r.nodes[i];
    nodes.append(py::dict(
        py::arg("role") = static_cast<int>(n->role), py::arg("id") = n->id,
        py::arg("data") = py::bytes(reinterpret_cast<const char *>(n->data),
                                    n->data_length)));
  }
  return py::dict(py::arg("role") = static_cast<int>(r.role),
                  py::arg("id") = r.id, py::arg("nodes") = nodes);
}

} // namespace

// The nlink_unpack results live in global singletons (g_nlt_*), but Feed()
// converts them to dicts synchronously while holding the GIL, so separate
// extractor instances never observe each other's data.
class LinkTrackExtractor {
public:
  LinkTrackExtractor() {
    Register(new ProtocolAnchorFrame0, "anchorframe0", &AnchorFrame0ToDict);
    Register(new ProtocolTagFrame0, "tagframe0", &TagFrame0ToDict);
    Register(new ProtocolNodeFrame0, "nodeframe0", &NodeFrame0ToDict);
    Register(new ProtocolNodeFrame1, "nodeframe1", &NodeFrame1ToDict);
    Register(new ProtocolNodeFrame2, "nodeframe2", &NodeFrame2ToDict);
    Register(new ProtocolNodeFrame3, "nodeframe3", &NodeFrame3ToDict);
    Register(new ProtocolNodeFrame4, "nodeframe4", &NodeFrame4ToDict);
    Register(new ProtocolNodeFrame5, "nodeframe5", &NodeFrame5ToDict);
    Register(new ProtocolNodeFrame6, "nodeframe6", &NodeFrame6ToDict);
  }

  void SetCallback(py::object callback) { callback_ = std::move(callback); }

  void Feed(py::bytes data) {
    std::string buffer = data;
    extracter_.AddNewData(reinterpret_cast<const uint8_t *>(buffer.data()),
                          buffer.size());
  }

private:
  void Register(NLinkProtocol *protocol, const char *frame_type,
                py::dict (*to_dict)()) {
    protocols_.emplace_back(protocol);
    protocol->SetHandleDataCallback([this, frame_type, to_dict] {
      if (!callback_.is_none()) {
        callback_(frame_type, to_dict());
      }
    });
    extracter_.AddProtocol(protocol);
  }

  NProtocolExtracter extracter_;
  std::vector<std::unique_ptr<NLinkProtocol>> protocols_;
  py::object callback_ = py::none();
};

PYBIND11_MODULE(_nlink_native, m) {
  m.doc() = "Nooploop LinkTrack NLink protocol parser (upstream C/C++ core)";

  py::class_<LinkTrackExtractor>(m, "LinkTrackExtractor")
      .def(py::init<>())
      .def("set_callback", &LinkTrackExtractor::SetCallback, py::arg("callback"),
           "Set fn(frame_type: str, frame: dict) invoked for every parsed frame")
      .def("feed", &LinkTrackExtractor::Feed, py::arg("data"),
           "Feed raw bytes from the serial stream; frames may span calls");
}
