//! DOS MZ executable parsing.
//!
//! PC-98 DOS programs use the same MZ header as IBM PC DOS. The header
//! gives us the initial code entry (CS:IP), the stack (SS:SP), the size
//! of the header and load module, and a table of relocations. For
//! disassembly we only need the entry point and the load module bytes;
//! relocations are parsed for completeness but not applied — they only
//! matter at load time, not for static analysis.
//!
//! Reference: MS-DOS Programmer's Reference, "EXE file header format".

use crate::image::{ImageError, Result};

const MZ_MAGIC: [u8; 2] = *b"MZ";
const MZ_HEADER_MIN: usize = 0x1C; // 14 standard little-endian words

/// Parsed DOS MZ file header.
#[derive(Debug, Clone)]
pub struct MzHeader {
    pub bytes_in_last_page: u16,
    pub pages: u16,
    pub reloc_count: u16,
    pub header_paragraphs: u16,
    pub min_alloc: u16,
    pub max_alloc: u16,
    pub initial_ss: u16,
    pub initial_sp: u16,
    pub checksum: u16,
    pub initial_ip: u16,
    pub initial_cs: u16,
    pub reloc_table_offset: u16,
    pub overlay: u16,
}

impl MzHeader {
    /// Header size in bytes. Always a multiple of 16.
    pub fn header_bytes(&self) -> u32 {
        self.header_paragraphs as u32 * 16
    }

    /// Size of the load module (executable image, excluding header).
    /// Computed from the page/last-page fields rather than the actual
    /// file size, since MZ allows overlays and trailing data.
    pub fn load_module_bytes(&self) -> u32 {
        let total = if self.pages == 0 {
            0
        } else {
            (self.pages as u32 - 1) * 512 + self.bytes_in_last_page as u32
        };
        total.saturating_sub(self.header_bytes())
    }

    /// Linear file offset of the entry point.
    pub fn entry_file_offset(&self) -> u32 {
        self.header_bytes() + self.entry_module_offset()
    }

    /// Entry point relative to the start of the load module.
    pub fn entry_module_offset(&self) -> u32 {
        self.initial_cs as u32 * 16 + self.initial_ip as u32
    }
}

/// A parsed MZ executable held in memory.
pub struct ExeFile {
    data: Vec<u8>,
    pub header: MzHeader,
}

impl ExeFile {
    pub fn from_bytes(data: Vec<u8>) -> Result<Self> {
        if data.len() < MZ_HEADER_MIN {
            return Err(ImageError::Truncated {
                expected: MZ_HEADER_MIN,
                actual: data.len(),
            });
        }
        if data[0..2] != MZ_MAGIC {
            return Err(ImageError::BadSignature { format: "MZ" });
        }

        let w = |off: usize| -> u16 {
            u16::from_le_bytes([data[off], data[off + 1]])
        };

        let header = MzHeader {
            bytes_in_last_page: w(0x02),
            pages: w(0x04),
            reloc_count: w(0x06),
            header_paragraphs: w(0x08),
            min_alloc: w(0x0A),
            max_alloc: w(0x0C),
            initial_ss: w(0x0E),
            initial_sp: w(0x10),
            checksum: w(0x12),
            initial_ip: w(0x14),
            initial_cs: w(0x16),
            reloc_table_offset: w(0x18),
            overlay: w(0x1A),
        };

        if header.header_paragraphs == 0 {
            return Err(ImageError::BadGeometry {
                field: "header_paragraphs",
                value: 0,
            });
        }
        let hdr_bytes = header.header_bytes();
        if hdr_bytes as usize > data.len() {
            return Err(ImageError::Truncated {
                expected: hdr_bytes as usize,
                actual: data.len(),
            });
        }

        Ok(Self { data, header })
    }

    /// The load module — the executable image with the header stripped.
    pub fn code_bytes(&self) -> &[u8] {
        &self.data[self.header.header_bytes() as usize..]
    }

    /// Read `length` bytes from the file at absolute file offset `offset`.
    pub fn read_at(&self, offset: u32, length: u32) -> Result<&[u8]> {
        let start = offset as usize;
        let end = start.saturating_add(length as usize);
        if end > self.data.len() {
            return Err(ImageError::Truncated {
                expected: end,
                actual: self.data.len(),
            });
        }
        Ok(&self.data[start..end])
    }

    /// Parse the relocation table. Each entry is `(offset, segment)`.
    pub fn relocations(&self) -> Vec<(u16, u16)> {
        let start = self.header.reloc_table_offset as usize;
        let mut out = Vec::with_capacity(self.header.reloc_count as usize);
        for i in 0..self.header.reloc_count as usize {
            let off = start + i * 4;
            if off + 4 > self.data.len() {
                break;
            }
            let offset = u16::from_le_bytes([self.data[off], self.data[off + 1]]);
            let segment = u16::from_le_bytes([self.data[off + 2], self.data[off + 3]]);
            out.push((offset, segment));
        }
        out
    }
}