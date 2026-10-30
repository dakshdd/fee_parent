
const months = [
    "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "January", "February", "March"
];

const LATE_FINE_PER_DAY = 5;
const DUE_DAY = 10;

// Calculate late fine: ₹5 per day after 10th
function calculateLateFine(month) {
    const today = new Date();
    const monthIndex = months.indexOf(month);

    if (monthIndex === -1) return 0;

    // April = 3, May = 4 ... March = 2
    const calendarMonth = (monthIndex + 3) % 12;
    let year = today.getFullYear();

    // January, February, March belong to next year
    if (calendarMonth <= 2 && today.getMonth() >= 3) {
        year++;
    }

    const dueDate = new Date(year, calendarMonth, DUE_DAY);
    const paymentDate = new Date(
        today.getFullYear(),
        today.getMonth(),
        today.getDate()
    );

    const lateDays = Math.max(
        Math.floor((paymentDate - dueDate) / 86400000),
        0
    );

    return lateDays * LATE_FINE_PER_DAY;
}

// Update monthly fee + late fine
function updateAmount(adm_code, month) {
    if (!adm_code || !month) return;

    fetch(
        "/fee/month_total?adm_code=" +
        encodeURIComponent(adm_code) +
        "&month=" + encodeURIComponent(month)
    )
        .then(res => {
            if (!res.ok) throw new Error("Fee calculation failed");
            return res.json();
        })
        .then(calc => {
            const monthlyFee = parseFloat(calc.total) || 0;
            const fine = calculateLateFine(month);

            document.getElementById("amountBox").value =
                monthlyFee.toFixed(2);

            document.getElementById("lateFeeBox").value =
                fine.toFixed(2);

            document.getElementById("feeInfo").innerHTML = `
                <p><b>Monthly Fee:</b> ₹${monthlyFee.toFixed(2)}</p>
                <p><b>Late Fine:</b> ₹${fine.toFixed(2)}</p>
                <p><b>Total Fee Amount:</b> ₹${monthlyFee.toFixed(2)}</p>
                <p><b>Total Collection:</b> ₹${(monthlyFee + fine).toFixed(2)}</p>
            `;
        })
        .catch(err => {
            console.error(err);
            document.getElementById("feeInfo").innerHTML =
                "<p>Unable to calculate fee. Please try again.</p>";
        });
}

// Autocomplete student search
document.getElementById("searchBox").addEventListener("keyup", function () {
    const q = this.value.trim();
    const list = document.getElementById("studentList");

    if (q.length < 1) {
        list.innerHTML = "";
        document.getElementById("details").innerHTML = "";
        return;
    }

    fetch("/fee/autocomplete?q=" + encodeURIComponent(q))
        .then(res => res.json())
        .then(data => {
            list.innerHTML = "";

            data.forEach(r => {
                const option = document.createElement("option");
                option.value = r.adm_code;
                option.textContent =
                    `${r.adm_code} | ${r.student_name} | ${r.class || "-"} | ${r.father_name || "-"}`;
                list.appendChild(option);
            });

            if (data.length === 1) {
                loadDetails(data[0].adm_code);
            }
        })
        .catch(err => console.error("Search error:", err));
});

// Load student details
function loadDetails(adm_code) {
    fetch("/fee/details?adm_code=" + encodeURIComponent(adm_code))
        .then(res => res.json())
        .then(r => {
            if (!r.adm_code) {
                document.getElementById("details").innerHTML =
                    "<p>No details found.</p>";
                return;
            }

            const html = `
                <h3>Student Details</h3>
                <p><b>Admission Code:</b> ${r.adm_code}</p>
                <p><b>Name:</b> ${r.student_name}</p>
                <p><b>Class:</b> ${r.class || "-"}</p>
                <p><b>Father:</b> ${r.father_name || "-"}</p>

                <form method="post" action="/fee/receive">
                    <input type="hidden" name="adm_code"
                           value="${r.adm_code}">

                    <label>Month</label>
                    <select name="month" id="monthSelect" required></select>

                    <label>Payment Mode</label>
                    <select name="mode" required>
                        <option value="Cash">Cash</option>
                        <option value="Cheque">Cheque</option>
                        <option value="UPI">UPI</option>
                    </select>

                    <label>Remark</label>
                    <input type="text" name="remark" id="remarkBox"
                           placeholder="Enter remark">

                    <div id="feeInfo"></div>

                    <label>Late Fee Fine (₹)</label>
                    <input type="number" step="0.01"
                           name="late_fee" id="lateFeeBox" readonly>

                    <label>Total Amount (₹)</label>
                    <input type="number" step="0.01"
                           name="amount" id="amountBox" required>

                    <button type="submit">Receive</button>
                </form>
            `;

            document.getElementById("details").innerHTML = html;

            const monthSelect = document.getElementById("monthSelect");

            months.forEach(m => {
                const opt = document.createElement("option");
                opt.value = m;
                opt.textContent = m;
                monthSelect.appendChild(opt);
            });

            // Get next payable month
            fetch("/fee/next_month?adm_code=" + encodeURIComponent(adm_code))
                .then(res => res.json())
                .then(data => {
                    if (data.month) {
                        monthSelect.value = data.month;
                    } else if (data.next_month) {
                        monthSelect.value = data.next_month;
                    }

                    // Disable already paid months
                    if (data.paid_months) {
                        data.paid_months.forEach(pm => {
                            const opt = [...monthSelect.options]
                                .find(o => o.value === pm);

                            if (opt) {
                                opt.disabled = true;
                                opt.textContent = pm + " (Paid)";
                            }
                        });
                    }

                    if (monthSelect.value) {
                        updateAmount(adm_code, monthSelect.value);
                    }
                })
                .catch(err => console.error("Next month error:", err));

            // Recalculate whenever month changes
            monthSelect.addEventListener("change", function () {
                updateAmount(adm_code, this.value);
            });
        })
        .catch(err => {
            console.error("Student details error:", err);
            document.getElementById("details").innerHTML =
                "<p>Unable to load student details.</p>";
        });
}

// Student selection
document.getElementById("studentList").addEventListener("change", function () {
    if (this.value) {
        loadDetails(this.value);
    }
});
