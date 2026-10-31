/*
 * mouse-sniffer - Raw-Fenster-Capture (Iteration 10)
 *
 * Nach dem endgueltigen Scheitern des nRF-Hardware-Adressmatchings (Iter
 * 5-9, vermutlich Bitfehler/Framing der Realtek-Maus) der pragmatische
 * "Raw-ish"-Ansatz:
 *
 *   - Pseudo-Promiscuous-Sync 0xAAAAAA (rastet auf die Preamble ein).
 *   - Aber STATLEN = GROSS (RAW_LEN Bytes ~= 1 ms Funkzeit): pro Sync wird
 *     ein langes Fenster mitgeschnitten -> faengt die ganze Paket-SALVE
 *     einer Aktion (Mäuse wiederholen Tasten/Scroll-Reports mehrfach).
 *   - Sofortiges Re-Arm, kaum Totzeit -> wir hoeren fast durchgehend zu.
 *   - RSSI-Filter haelt Rauschen raus.
 *
 * Ausrichtung auf 52 b1 5a db + Decodierung macht der Host (frames.py),
 * fehlertolerant. Laeuft auf beiden Boards gleichzeitig -> doppelte Rate.
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <hal/nrf_radio.h>

#define RX_CHANNEL 50
#define RX_MODE NRF_RADIO_MODE_NRF_2MBIT

/* Grosses Fenster. PCNF1 STATLEN/MAXLEN sind 8 Bit -> max 255. */
#define RAW_LEN 200

#define PROMISC_BALEN 2
#define PROMISC_BASE0 0xAAAA0000UL
#define PROMISC_PREFIX 0xAA

#define PRINT_RSSI_MIN (-72)
#define RX_TIMEOUT_US 1500
#define PRINT_INTERVAL_MS 70   /* begrenzt die 200-Byte-Zeilen fuer USB-CDC */
#define HEARTBEAT_MS 1000

static uint8_t rx_buf[RAW_LEN + 4] __aligned(4);

static void radio_init(void)
{
	nrf_radio_power_set(NRF_RADIO, true);
	nrf_radio_txpower_set(NRF_RADIO, NRF_RADIO_TXPOWER_0DBM);
	nrf_radio_mode_set(NRF_RADIO, RX_MODE);
	nrf_radio_frequency_set(NRF_RADIO, 2400 + RX_CHANNEL);

	nrf_radio_packet_conf_t pcnf = {
		.lflen = 0, .s0len = 0, .s1len = 0,
		.maxlen = RAW_LEN, .statlen = RAW_LEN,
		.balen = PROMISC_BALEN,
		.big_endian = true,
		.whiteen = false,
		.plen = NRF_RADIO_PREAMBLE_LENGTH_8BIT,
	};
	nrf_radio_packet_configure(NRF_RADIO, &pcnf);
	nrf_radio_base0_set(NRF_RADIO, PROMISC_BASE0);
	nrf_radio_prefix0_set(NRF_RADIO, PROMISC_PREFIX);
	nrf_radio_rxaddresses_set(NRF_RADIO, 1u << 0);
	nrf_radio_crc_configure(NRF_RADIO, 0, NRF_RADIO_CRC_ADDR_INCLUDE, 0);
	nrf_radio_shorts_set(NRF_RADIO,
			     NRF_RADIO_SHORT_READY_START_MASK |
			     NRF_RADIO_SHORT_ADDRESS_RSSISTART_MASK |
			     NRF_RADIO_SHORT_END_DISABLE_MASK);
}

static int rx_one(int16_t *rssi)
{
	nrf_radio_event_clear(NRF_RADIO, NRF_RADIO_EVENT_END);
	nrf_radio_packetptr_set(NRF_RADIO, rx_buf);
	nrf_radio_task_trigger(NRF_RADIO, NRF_RADIO_TASK_RXEN);
	uint32_t waited = 0;
	while (!nrf_radio_event_check(NRF_RADIO, NRF_RADIO_EVENT_END)) {
		k_busy_wait(1);
		if (++waited >= RX_TIMEOUT_US) {
			nrf_radio_task_trigger(NRF_RADIO, NRF_RADIO_TASK_DISABLE);
			while (nrf_radio_state_get(NRF_RADIO) !=
			       NRF_RADIO_STATE_DISABLED) {
				k_busy_wait(1);
			}
			return 0;
		}
	}
	*rssi = -(int16_t)nrf_radio_rssi_sample_get(NRF_RADIO);
	while (nrf_radio_state_get(NRF_RADIO) != NRF_RADIO_STATE_DISABLED) {
		k_busy_wait(1);
	}
	return 1;
}

int main(void)
{
	printk("\nmouse-sniffer: Raw-Fenster-Capture (Iteration 10)\n");
	printk("CH%d=%dMHz 2MBIT, Fenster %d Byte, Sync AAAAAA, CRC aus\n",
	       RX_CHANNEL, 2400 + RX_CHANNEL, RAW_LEN);
	printk("Nur RSSI >= %d dBm. Host richtet auf 52 b1 5a db aus.\n\n",
	       PRINT_RSSI_MIN);

	k_msleep(200);
	radio_init();

	uint32_t total = 0, strong = 0, hb_t = 0, hb_s = 0;
	int16_t rssi = 0, last_rssi = 0;
	int64_t t_print = 0, t_hb = 0;

	while (1) {
		int64_t now = k_uptime_get();

		if (rx_one(&rssi)) {
			total++;
			if (rssi >= PRINT_RSSI_MIN) {
				strong++;
				last_rssi = rssi;
				if (now - t_print >= PRINT_INTERVAL_MS) {
					t_print = now;
					printk("PKT rssi=%d :", rssi);
					for (int i = 0; i < RAW_LEN; i++) {
						printk(" %02x", rx_buf[i]);
					}
					printk("\n");
				}
			}
		}

		if (now - t_hb >= HEARTBEAT_MS) {
			printk("HB  total=%u (+%u/s) strong=%u (+%u) last_rssi=%d\n",
			       total, total - hb_t, strong, strong - hb_s,
			       last_rssi);
			hb_t = total; hb_s = strong;
			t_hb = now;
		}
		k_msleep(1);
	}
	return 0;
}
