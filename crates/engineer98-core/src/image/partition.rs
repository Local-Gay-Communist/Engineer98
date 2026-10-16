use super::error::Result;
use super::geometry::{CHS, Geometry};

/// One entry in the PC-98 IPL1 partition table.
#[derive(Debug, Clone)]
pub struct Partition {
    pub name: String,
    pub start_lba: u32,
    pub sector_count: u32,
    pub bootable: bool,
}

/// PC-98 IPL1 layout:
///   sector 0: MBR, starts with EB xx xx xx IPL1, ends with 55 AA
///   sector 1: 16 entries × 32 bytes each
///   sectors 2-15: boot code
///   sectors 16+: partition contents
pub fn read_ipl1(data: &[u8], data_offset: usize, geom: Geometry) -> Result<Vec<Partition>> {
    let mut out = Vec::new();
    if data.len() < data_offset + geom.sector_size as usize * 2 {
        return Ok(out);
    }

    // Verify the magic: IPL1 at offset 4 of sector 0, boot flag at end.
    let sector0 = &data[data_offset..data_offset + geom.sector_size as usize];
    let has_magic = sector0.len() >= 8 && &sector0[4..8] == b"IPL1";
    let has_boot_flag = sector0.len() >= 512
        && sector0[510] == 0x55
        && sector0[511] == 0xAA;

    if !has_magic && !has_boot_flag {
        return Ok(out);
    }

    // Partition table starts at sector 1.
    let table_off = data_offset + geom.sector_size as usize;
    for i in 0..16 {
        let entry = table_off + i * 32;
        if entry + 32 > data.len() {
            break;
        }
        let mid = data[entry];
        let _sid = data[entry + 1];
        let _ipl_sector = data[entry + 4];
        let _ipl_head = data[entry + 5];
        let _ipl_cyl = u16::from_le_bytes([data[entry + 6], data[entry + 7]]);
        let start_sector_raw = data[entry + 8];
        let start_head = data[entry + 9];
        let start_cyl = u16::from_le_bytes([data[entry + 10], data[entry + 11]]);
        let end_sector_raw = data[entry + 12];
        let end_head = data[entry + 13];
        let end_cyl = u16::from_le_bytes([data[entry + 14], data[entry + 15]]);
        let name_bytes = &data[entry + 16..entry + 32];

        // Skip empty entries: all start fields zero.
        if start_sector_raw == 0 && start_head == 0 && start_cyl == 0 {
            continue;
        }

        // PC-98 IPLTBL nominally uses 1-based sector numbers, but Anex86
        // and some other formatters write 0 meaning "the first sector of
        // the cylinder". Normalize 0 → 1 before CHS conversion.
        let start = CHS {
            cylinder: start_cyl,
            head: start_head,
            sector: if start_sector_raw == 0 { 1 } else { start_sector_raw },
        };
        let end = CHS {
            cylinder: end_cyl,
            head: end_head,
            sector: if end_sector_raw == 0 { 1 } else { end_sector_raw },
        };

        let name = String::from_utf8_lossy(name_bytes)
            .trim_end_matches('\0')
            .trim()
            .to_string();

        let (Some(start_lba), Some(end_lba)) = (
            geom.chs_to_lba(start),
            geom.chs_to_lba(end),
        ) else {
            continue;
        };

        out.push(Partition {
            name,
            start_lba,
            sector_count: end_lba.saturating_sub(start_lba) + 1,
            bootable: mid != 0,
        });
    }

    Ok(out)
}