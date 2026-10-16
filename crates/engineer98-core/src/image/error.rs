use std::fmt;

#[derive(Debug)]
pub enum ImageError {
    Io(std::io::Error),
    /// File is too short to contain the header this format requires.
    Truncated { expected: usize, actual: usize },
    /// Header exists but a magic number / signature didn't match.
    BadSignature { format: &'static str },
    /// Geometry field is zero or otherwise unusable.
    BadGeometry { field: &'static str, value: u64 },
    /// Requested sector is outside the image.
    OutOfRange { lba: u32, max: u32 },
    /// Format recognised, but the specific variant isn't supported yet.
    Unsupported(&'static str),
}

impl fmt::Display for ImageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(e) => write!(f, "I/O error: {e}"),
            Self::Truncated { expected, actual } => {
                write!(f, "file truncated: need {expected} bytes, have {actual}")
            }
            Self::BadSignature { format } => write!(f, "bad signature for {format}"),
            Self::BadGeometry { field, value } => {
                write!(f, "invalid geometry: {field} = {value}")
            }
            Self::OutOfRange { lba, max } => {
                write!(f, "LBA {lba} out of range (max {max})")
            }
            Self::Unsupported(s) => write!(f, "unsupported: {s}"),
        }
    }
}

impl std::error::Error for ImageError {}

impl From<std::io::Error> for ImageError {
    fn from(e: std::io::Error) -> Self {
        Self::Io(e)
    }
}

pub type Result<T> = std::result::Result<T, ImageError>;