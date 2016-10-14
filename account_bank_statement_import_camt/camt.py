# -*- coding: utf-8 -*-
# © 2013-2016 Therp BV <http://therp.nl>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import re
from datetime import datetime
from lxml import etree

from openerp import _
from openerp.addons.account_bank_statement_import.parserlib import (
    BankStatement)


class CamtParser(object):
    """Parser for camt bank statement import files."""

    def parse_amount(self, ns, node):
        """Parse element that contains Amount and CreditDebitIndicator."""
        if node is None:
            return 0.0
        sign = 1
        amount = 0.0
        sign_node = node.xpath('ns:CdtDbtInd', namespaces={'ns': ns})
        if sign_node and sign_node[0].text == 'DBIT':
            sign = -1
        amount_node = node.xpath('ns:Amt', namespaces={'ns': ns})
        if amount_node:
            amount = sign * float(amount_node[0].text)
        return amount

    def add_value_from_node(
            self, ns, node, xpath_str, obj, attr_name, join_str=None):
        """Add value to object from first or all nodes found with xpath.

        If xpath_str is a list (or iterable), it will be seen as a series
        of search path's in order of preference. The first item that results
        in a found node will be used to set a value."""
        if not isinstance(xpath_str, (list, tuple)):
            xpath_str = [xpath_str]
        for search_str in xpath_str:
            found_node = node.xpath(search_str, namespaces={'ns': ns})
            if found_node:
                if join_str is None:
                    attr_value = found_node[0].text
                else:
                    attr_value = join_str.join([x.text for x in found_node])
                setattr(obj, attr_name, attr_value)
                break

    def parse_transaction_details(self, ns, node, transaction):
        """Parse transaction details (message, party, account...)."""
        # message
        self.add_value_from_node(
            ns, node, [
                './ns:RmtInf/ns:Ustrd',
                './ns:AddtlTxInf',
                './ns:AddtlNtryInf',
            ], transaction, 'message', join_str='\n')
        # eref
        self.add_value_from_node(
            ns, node, [
                './ns:RmtInf/ns:Strd/ns:CdtrRefInf/ns:Ref',
                './ns:Refs/ns:EndToEndId',
            ],
            transaction, 'eref'
        )
        # remote party values
        party_type = 'Dbtr'
        party_type_node = node.xpath(
            '../../ns:CdtDbtInd', namespaces={'ns': ns})
        if party_type_node and party_type_node[0].text != 'CRDT':
            party_type = 'Cdtr'
        party_node = node.xpath(
            './ns:RltdPties/ns:%s' % party_type, namespaces={'ns': ns})
        if party_node:
            self.add_value_from_node(
                ns, party_node[0], './ns:Nm', transaction, 'remote_owner')
            self.add_value_from_node(
                ns, party_node[0], './ns:PstlAdr/ns:Ctry', transaction,
                'remote_owner_country'
            )
            address_node = party_node[0].xpath(
                './ns:PstlAdr/ns:AdrLine', namespaces={'ns': ns})
            if address_node:
                transaction.remote_owner_address = [address_node[0].text]
        # Get remote_account from iban or from domestic account:
        account_node = node.xpath(
            './ns:RltdPties/ns:%sAcct/ns:Id' % party_type,
            namespaces={'ns': ns}
        )
        if account_node:
            iban_node = account_node[0].xpath(
                './ns:IBAN', namespaces={'ns': ns})
            if iban_node:
                transaction.remote_account = iban_node[0].text
                bic_node = node.xpath(
                    './ns:RltdAgts/ns:%sAgt/ns:FinInstnId/ns:BIC' % party_type,
                    namespaces={'ns': ns}
                )
                if bic_node:
                    transaction.remote_bank_bic = bic_node[0].text
            else:
                self.add_value_from_node(
                    ns, account_node[0], './ns:Othr/ns:Id', transaction,
                    'remote_account'
                )

    def parse_transaction(self, ns, node, transaction):
        """Parse transaction (entry) node."""
        self.add_value_from_node(
            ns, node, './ns:BkTxCd/ns:Prtry/ns:Cd', transaction,
            'transfer_type'
        )
        self.add_value_from_node(
            ns, node, './ns:BookgDt/ns:Dt', transaction, 'execution_date')
        self.add_value_from_node(
            ns, node, './ns:ValDt/ns:Dt', transaction, 'value_date')
        transaction.transferred_amount = self.parse_amount(ns, node)
        details_node = node.xpath(
            './ns:NtryDtls/ns:TxDtls', namespaces={'ns': ns})
        if details_node:
            self.parse_transaction_details(ns, details_node[0], transaction)
        if not transaction.message:
            self.add_value_from_node(
                ns, node, './ns:AddtlNtryInf', transaction, 'message')
        if not transaction.eref:
            self.add_value_from_node(
                ns, node, [
                    './ns:NtryDtls/ns:Btch/ns:PmtInfId',
                ],
                transaction, 'eref'
            )
        transaction.data = etree.tostring(node)
        return transaction

    def get_balance_type_node(self, node, balance_type):
        """
        :param node: BkToCstmrStmt/Stmt/Bal node
        :param balance type: one of 'OPBD', 'PRCD', 'ITBD', 'CLBD'
        """
        code_expr = (
            './ns:Bal/ns:Tp/ns:CdOrPrtry/ns:Cd[text()="%s"]/../../..' %
            balance_type
        )
        return self.xpath(node, code_expr)

    def get_start_balance(self, node):
        """
        Find the (only) balance node with code OpeningBalance, or
        the only one with code 'PreviousClosingBalance'
        or the first balance node with code InterimBalance in
        the case of preceeding pagination.

        :param node: BkToCstmrStmt/Stmt/Bal node
        """
        balance = 0
        nodes = (
            self.get_balance_type_node(node, 'OPBD') or
            self.get_balance_type_node(node, 'PRCD') or
            self.get_balance_type_node(node, 'ITBD')
        )
        if nodes:
            balance = self.parse_amount(nodes[0])
        return balance

    def get_end_balance(self, node):
        """
        Find the (only) balance node with code ClosingBalance, or
        the second (and last) balance node with code InterimBalance in
        the case of continued pagination.

        :param node: BkToCstmrStmt/Stmt/Bal node
        """
        balance = 0
        nodes = (
            self.get_balance_type_node(node, 'CLAV') or
            self.get_balance_type_node(node, 'CLBD') or
            self.get_balance_type_node(node, 'ITBD')
        )
        if nodes:
            balance = self.parse_amount(nodes[-1])
        return balance

    def parse_statement(self, ns, node):
        """Parse a single Stmt node."""
        statement = BankStatement()
        self.add_value_from_node(
            ns, node, [
                './ns:Acct/ns:Id/ns:IBAN',
                './ns:Acct/ns:Id/ns:Othr/ns:Id',
            ], statement, 'local_account'
        )
        self.add_value_from_node(
            ns, node, './ns:Id', statement, 'statement_id')
        self.add_value_from_node(
            ns, node, './ns:Acct/ns:Ccy', statement, 'local_currency')
        statement.start_balance = self.get_start_balance(node)
        statement.end_balance = self.get_end_balance(node)
        transaction_nodes = node.xpath('./ns:Ntry', namespaces={'ns': ns})
        total_amount = 0
        for entry_node in transaction_nodes:
            transaction = statement.create_transaction()
            total_amount += transaction['transferred_amount']
            transaction.data = etree.tostring(entry_node)
            self.parse_transaction(ns, entry_node, transaction)
        if statement['transactions']:
            execution_date = statement['transactions'][0].execution_date
            statement.date = datetime.strptime(execution_date, "%Y-%m-%d")
            # Prepend date of first transaction to improve id uniquenes
            if execution_date not in statement.statement_id:
                statement.statement_id = "%s-%s" % (
                    execution_date, statement.statement_id)
        if statement.start_balance == 0 and statement.end_balance != 0:
            statement.start_balance = statement.end_balance - total_amount
            _logger.debug(
                _("Start balance %s calculated from end balance %s and"
                  " Total amount %s."),
                statement.start_balance,
                statement.end_balance,
                total_amount
            )
        return statement

    def check_version(self, ns, root):
        """Validate validity of camt file."""
        # Check wether it is camt at all:
        re_camt = re.compile(
            r'(^urn:iso:std:iso:20022:tech:xsd:camt.'
            r'|^ISO:camt.)'
        )
        if not re_camt.search(ns):
            raise ValueError('no camt: ' + ns)
        # Check wether version 052 or 053:
        re_camt_version = re.compile(
            r'(^urn:iso:std:iso:20022:tech:xsd:camt.053.'
            r'|^urn:iso:std:iso:20022:tech:xsd:camt.052.'
            r'|^ISO:camt.053.'
            r'|^ISO:camt.052.)'
        )
        if not re_camt_version.search(ns):
            raise ValueError('no camt 052 or 053: ' + ns)
        # Check GrpHdr element:
        root_0_0 = root[0][0].tag[len(ns) + 2:]  # strip namespace
        if root_0_0 != 'GrpHdr':
            raise ValueError('expected GrpHdr, got: ' + root_0_0)

    def parse(self, data):
        """Parse a camt.052 or camt.053 file."""
        try:
            root = etree.fromstring(
                data, parser=etree.XMLParser(recover=True))
        except etree.XMLSyntaxError:
            # ABNAmro is known to mix up encodings
            root = etree.fromstring(
                data.decode('iso-8859-15').encode('utf-8'))
        if root is None:
            raise ValueError(
                'Not a valid xml file, or not an xml file at all.')
        ns = root.tag[1:root.tag.index("}")]
        self.check_version(ns, root)
        statements = []
        for node in root[0][1:]:
            statement = self.parse_statement(ns, node)
            if len(statement['transactions']):
                statements.append(statement)
        return statements
