"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { useTranslations } from "next-intl";

import {
  getBookingCatalog,
  listMemberships,
  updateBookingStaff,
  type BookingCatalog,
  type MembershipSummary,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { NativeSelect } from "@saas-core/ui/components/native-select";

type Staff = BookingCatalog["staff"][number];

function memberName(member: MembershipSummary): string {
  const name = [member.first_name, member.last_name].join(" ").trim();
  return name ? `${name} (${member.email})` : member.email;
}

/**
 * Which team member a calendar staff member is. Until they are linked, the
 * member's own visits cannot be told apart ("Mine" on Today stays empty), so
 * the team screen offers the link next to the people it concerns.
 */
export function StaffAccountsCard() {
  const t = useTranslations("StaffAccounts");
  const [staff, setStaff] = useState<Staff[]>();
  const [members, setMembers] = useState<MembershipSummary[]>([]);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [saved, setSaved] = useState<string>();

  const load = useCallback(async () => {
    try {
      const [catalog, memberships] = await Promise.all([
        getBookingCatalog(),
        listMemberships(),
      ]);
      setStaff(catalog.staff);
      setMembers(memberships.filter((member) => member.status === "active"));
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void load();
  }, [load]);

  async function link(item: Staff, membershipId: string | null) {
    setSaving(item.id);
    setProblem(undefined);
    setSaved(undefined);
    try {
      const updated = await updateBookingStaff(item.id, {
        membership_id: membershipId,
      });
      setStaff((current) =>
        current?.map((row) =>
          row.id === updated.id ? { ...row, ...updated } : row,
        ),
      );
      setSaved(t("saved", { name: item.name }));
    } catch {
      setProblem(t("error", { name: item.name }));
    } finally {
      setSaving(undefined);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {failed ? (
          <div className="flex flex-wrap items-center gap-3" role="alert">
            <p className="text-sm text-destructive">{t("loadError")}</p>
            <Button
              onClick={() => {
                setFailed(false);
                void load();
              }}
              variant="outline"
            >
              {t("retry")}
            </Button>
          </div>
        ) : !staff ? (
          <div
            aria-busy="true"
            className="h-24 animate-pulse rounded-lg bg-muted"
          />
        ) : staff.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        ) : (
          <ul className="divide-y">
            {staff.map((item) => (
              <StaffRow
                disabled={saving !== undefined}
                item={item}
                key={item.id}
                // One account per calendar person: a member linked elsewhere
                // is offered, but marked, so a move is deliberate.
                linkedElsewhere={
                  new Set(
                    staff
                      .filter((row) => row.id !== item.id && row.membership_id)
                      .map((row) => row.membership_id!),
                  )
                }
                members={members}
                onLink={(membershipId) => void link(item, membershipId)}
              />
            ))}
          </ul>
        )}
        <p aria-live="polite" className="text-sm text-success-foreground">
          {saved}
        </p>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function StaffRow({
  item,
  members,
  linkedElsewhere,
  disabled,
  onLink,
}: {
  item: Staff;
  members: MembershipSummary[];
  linkedElsewhere: Set<string>;
  disabled: boolean;
  onLink: (membershipId: string | null) => void;
}) {
  const t = useTranslations("StaffAccounts");
  const id = useId();
  return (
    <li className="grid gap-2 py-3 sm:grid-cols-[1fr_minmax(0,22rem)] sm:items-center">
      <label className="font-medium" htmlFor={id}>
        {item.name}
      </label>
      <NativeSelect
        disabled={disabled}
        id={id}
        onChange={(event) => onLink(event.target.value || null)}
        value={item.membership_id ?? ""}
      >
        <option value="">{t("noAccount")}</option>
        {members.map((member) => (
          <option key={member.id} value={member.id}>
            {linkedElsewhere.has(member.id)
              ? t("linkedElsewhere", { name: memberName(member) })
              : memberName(member)}
          </option>
        ))}
      </NativeSelect>
    </li>
  );
}
