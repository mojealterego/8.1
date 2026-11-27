//! Bounded wire framing for omnicore.rpc.v1. Authorization and JSON validation
//! remain server responsibilities; this module does not implement Zenoh or TLS.
use std::os::raw::{c_int, c_uchar, c_uint};

pub const MAX_FRAME_BYTES: usize = 65_536;

extern "C" {
    fn ocr_frame_encode(length: c_uint, header: *mut c_uchar) -> c_int;
    fn ocr_frame_decode(header: *const c_uchar, length: *mut c_uint) -> c_int;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FrameError { InvalidLength, NativeContract }

pub fn encode_header(length: usize) -> Result<[u8; 4], FrameError> {
    if !(1..=MAX_FRAME_BYTES).contains(&length) { return Err(FrameError::InvalidLength); }
    let mut header = [0u8; 4];
    // SAFETY: header is writable for exactly four bytes and length fits c_uint.
    match unsafe { ocr_frame_encode(length as c_uint, header.as_mut_ptr()) } {
        0 => Ok(header), 2 => Err(FrameError::InvalidLength), _ => Err(FrameError::NativeContract),
    }
}

pub fn decode_header(header: [u8; 4]) -> Result<usize, FrameError> {
    let mut length: c_uint = 0;
    // SAFETY: header has four readable bytes; length is aligned and writable.
    match unsafe { ocr_frame_decode(header.as_ptr(), &mut length) } {
        0 if (1..=MAX_FRAME_BYTES).contains(&(length as usize)) => Ok(length as usize),
        2 => Err(FrameError::InvalidLength), _ => Err(FrameError::NativeContract),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exhaustive_headers() {
        for n in 1..=MAX_FRAME_BYTES {
            assert_eq!(encode_header(n), Ok((n as u32).to_be_bytes()));
            assert_eq!(decode_header((n as u32).to_be_bytes()), Ok(n));
        }
    }
    #[test]
    fn bounds() {
        for n in [0, MAX_FRAME_BYTES + 1, usize::MAX] {
            assert_eq!(encode_header(n), Err(FrameError::InvalidLength));
        }
        for h in [[0; 4], [255; 4], [0, 1, 0, 1]] {
            assert_eq!(decode_header(h), Err(FrameError::InvalidLength));
        }
    }
}
