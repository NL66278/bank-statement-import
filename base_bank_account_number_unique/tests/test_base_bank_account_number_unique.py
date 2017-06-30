# -*- coding: utf-8 -*-
# © 2015-2017 Therp BV <https://therp.nl>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from openerp.tests.common import TransactionCase
from openerp.exceptions import ValidationError


class TestBaseBankAccountNumberUnique(TransactionCase):

    def test_base_bank_account_number_unique(self):
        """Add a bank account, then try to add another one with the
        same number."""
        bank_account_model = self.env['res.partner.bank']
        bank_account_model.create({
            'acc_number': 'BE1234567890',
            'state': 'bank',
        })
        bank_account_model.create({
            'acc_number': 'BE 1234 567 890',
            'state': 'bank',
        })
        with self.assertRaises(ValidationError):
            bank_account_model.create({
                'acc_number': 'BE 1234 567 890',
                'state': 'bank',
            })
