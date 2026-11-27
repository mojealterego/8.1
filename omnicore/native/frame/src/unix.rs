//! Synchronous bounded AF_UNIX client. Transport success is not RPC success.
use crate::MAX_FRAME_BYTES;
use std::ffi::CString;
use std::os::raw::{c_char, c_int};
use std::os::unix::ffi::OsStrExt;
use std::path::Path;

extern "C" {
    fn ocr_unix_exchange_ffi(
        path: *const c_char, uid: u32, label: *const c_char, timeout_ms: u32,
        request: *const u8, request_len: usize, response: *mut u8, capacity: usize,
        response_len: *mut usize,
    ) -> c_int;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnixError {
    Argument, Io, Timeout, UntrustedPeer, Protocol, Capacity, NativeContract,
}

/// Construct from trusted local configuration, never from remote RPC data.
#[derive(Debug)]
pub struct UnixClient {
    path: CString,
    uid: u32,
    label: CString,
    timeout_ms: u32,
}

impl UnixClient {
    pub fn new(path: &Path, uid: u32, label: &[u8], timeout_ms: u32) -> Result<Self, UnixError> {
        let bytes = path.as_os_str().as_bytes();
        if !path.is_absolute() || !(2..=107).contains(&bytes.len())
            || !(1..=256).contains(&label.len()) || !(1..=5000).contains(&timeout_ms) {
            return Err(UnixError::Argument);
        }
        Ok(Self {
            path: CString::new(bytes).map_err(|_| UnixError::Argument)?,
            uid,
            label: CString::new(label).map_err(|_| UnixError::Argument)?,
            timeout_ms,
        })
    }

    /// Returns only the initialized response prefix. On error a bounded output
    /// buffer is cleared. Do not retry automatically: a request may have run.
    /// The caller must validate the RPC response schema, status and request ID.
    pub fn exchange<'a>(&self, request: &[u8], response: &'a mut [u8]) -> Result<&'a [u8], UnixError> {
        if !(1..=MAX_FRAME_BYTES).contains(&response.len()) {
            return Err(UnixError::Argument);
        }
        if !(1..=MAX_FRAME_BYTES).contains(&request.len()) {
            response.fill(0);
            return Err(UnixError::Argument);
        }
        let mut length = 0usize;
        // SAFETY: CStrings are NUL-terminated and live throughout the call;
        // Rust borrows ensure valid, disjoint request/response storage.
        // The C shim uses uint32_t, int and size_t matching this declaration.
        let code = unsafe {
            ocr_unix_exchange_ffi(self.path.as_ptr(), self.uid, self.label.as_ptr(),
                self.timeout_ms, request.as_ptr(), request.len(), response.as_mut_ptr(),
                response.len(), &mut length)
        };
        if code == 0 && (1..=response.len()).contains(&length) {
            return Ok(&response[..length]);
        }
        response.fill(0);
        Err(match code {
            1 => UnixError::Argument,
            2 => UnixError::Io,
            3 => UnixError::Timeout,
            4 => UnixError::UntrustedPeer,
            5 => UnixError::Protocol,
            6 => UnixError::Capacity,
            _ => UnixError::NativeContract,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_bad_config() {
        for path in ["relative", "/", "/bad\0path"] {
            assert!(matches!(UnixClient::new(Path::new(path), 0, b"kernel", 100), Err(UnixError::Argument)));
        }
        assert!(UnixClient::new(Path::new("/x"), 0, b"bad\0label", 100).is_err());
        assert!(UnixClient::new(Path::new("/x"), 0, b"", 100).is_err());
        assert!(UnixClient::new(Path::new("/x"), 0, b"kernel", 5001).is_err());
    }

    #[test]
    fn invalid_request_clears_bounded_output() {
        let client = UnixClient::new(Path::new("/x"), 0, b"kernel", 100).unwrap();
        let mut response = [0xA5; 16];
        assert_eq!(client.exchange(b"", &mut response), Err(UnixError::Argument));
        assert_eq!(response, [0; 16]);
        assert_eq!(client.exchange(b"{}", &mut []), Err(UnixError::Argument));
    }
}
