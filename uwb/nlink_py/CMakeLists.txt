cmake_minimum_required(VERSION 3.18)
project(nlink_py LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(pybind11 CONFIG REQUIRED)

set(NLINK_EXTERN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../extern")
if(NOT EXISTS "${NLINK_EXTERN_DIR}/protocol_extracter/nprotocol_extracter.cpp"
   OR NOT EXISTS "${NLINK_EXTERN_DIR}/nlink_unpack/nlink_utils.c")
  message(FATAL_ERROR
    "Nooploop sources not found in ${NLINK_EXTERN_DIR}. "
    "Run: git submodule update --init --recursive")
endif()

pybind11_add_module(_nlink_native
  src/cpp/bindings.cpp
  src/cpp/linktrack_protocols.cpp
  ${NLINK_EXTERN_DIR}/protocol_extracter/nprotocol_base.cpp
  ${NLINK_EXTERN_DIR}/protocol_extracter/nprotocol_extracter.cpp
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_utils.c
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_linktrack_anchorframe0.c
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_linktrack_tagframe0.c
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_linktrack_nodeframe0.c
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_linktrack_nodeframe1.c
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_linktrack_nodeframe2.c
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_linktrack_nodeframe3.c
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_linktrack_nodeframe4.c
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_linktrack_nodeframe5.c
  ${NLINK_EXTERN_DIR}/nlink_unpack/nlink_linktrack_nodeframe6.c
)

target_include_directories(_nlink_native PRIVATE ${NLINK_EXTERN_DIR})

install(TARGETS _nlink_native DESTINATION nlink_py)
